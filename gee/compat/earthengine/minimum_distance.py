"""Bounded static minimum-distance classifiers over inline Features."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

from .array_core import charge_array
from .feature_values import is_collection, validate_feature
from .ir import fail, integer
from .minimum_distance_metrics import predict_unique, require_metric


MAX_TRAINING_FEATURES = 1_000
MAX_INPUT_PROPERTIES = 8
MAX_CLASSES = 64
MAX_EXACT_INTEGER = 2 ** 53

CLASSIFIER_FUNCTIONS = frozenset({
    "Classifier.minimumDistance", "Classifier.train",
    "Classifier.schema", "Classifier.setOutputMode",
})


@dataclass(frozen=True)
class StaticMinimumDistance:
    """Immutable classifier state; centers are label-major, then schema order."""

    metric: str = "euclidean"
    k_nearest: int = 1
    output_mode: str = "CLASSIFICATION"
    schema: tuple[str, ...] | None = None
    labels: tuple[int, ...] = ()
    centers: tuple[tuple[Fraction, ...], ...] = ()
    training_rows: tuple[tuple[int, tuple[Fraction, ...]], ...] = ()

def _number_fraction(value, label, *, allow_fraction=False):
    if type(value) is int:
        if abs(value) > MAX_EXACT_INTEGER:
            fail(f"{label} integer is outside the exact Float64 domain")
        return Fraction(value)
    if type(value) is float:
        if not math.isfinite(value):
            fail(f"{label} must be finite numeric data")
        return Fraction.from_float(value)
    if allow_fraction and isinstance(value, Fraction):
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if finite:
            return value
    fail(f"{label} must be finite numeric data")

def _label(value):
    if isinstance(value, bool) or type(value) not in (int, float):
        fail("Classifier class labels must be integers from 0 through 63")
    if type(value) is float and not math.isfinite(value):
        fail("Classifier class labels must be integers from 0 through 63")
    if int(value) != value or not 0 <= value < MAX_CLASSES:
        fail("Classifier class labels must be integers from 0 through 63")
    return int(value)

def _supported(classifier):
    if not isinstance(classifier, StaticMinimumDistance):
        fail("Expected a supported ee.Classifier.minimumDistance")
    require_metric(classifier.metric)
    if type(classifier.k_nearest) is not int or classifier.k_nearest != 1:
        fail("Only minimum-distance classifiers with kNearest=1 are supported")
    if (type(classifier.output_mode) is not str
            or classifier.output_mode != "CLASSIFICATION"):
        fail("Only CLASSIFICATION output mode is supported for minimum distance")
    return classifier

def require_trained(value):
    """Require a supported, trained model and return its immutable IR value."""
    classifier = _supported(value)
    if (not isinstance(classifier.schema, tuple) or not classifier.schema
            or len(classifier.schema) > MAX_INPUT_PROPERTIES
            or any(type(name) is not str or not name or "." in name
                   for name in classifier.schema)
            or len(set(classifier.schema)) != len(classifier.schema)
            or not classifier.labels or len(classifier.labels) > MAX_CLASSES
            or len(classifier.centers) != len(classifier.labels)
            or not classifier.training_rows):
        fail("Classifier must be trained on a nonempty inline FeatureCollection")
    if any(len(center) != len(classifier.schema) for center in classifier.centers):
        fail("Classifier model has inconsistent center dimensions")
    return classifier

def _input_properties(translator, value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_INPUT_PROPERTIES:
        fail(f"Classifier inputProperties must be a list of 1..{MAX_INPUT_PROPERTIES} names")
    charge_array(translator, len(value))
    if any(not isinstance(name, str) or not name or "." in name for name in value):
        fail("Classifier inputProperties must contain nonempty flat property names")
    charge_array(translator, sum(len(name) for name in value))
    if len(set(value)) != len(value):
        fail("Classifier inputProperties must be unique")
    return tuple(value)

def _features(translator, value):
    if not is_collection(value) or not isinstance(value.get("features"), list):
        fail("Classifier.train requires an inline FeatureCollection")
    features = value["features"]
    if not features or len(features) > MAX_TRAINING_FEATURES:
        fail(f"Classifier.train requires 1..{MAX_TRAINING_FEATURES} inline Features")
    charge_array(translator, len(features))
    for feature in features:
        checked = validate_feature(translator, feature)
        properties = checked["properties"]
        charge_array(translator, len(properties))
        for name in properties:
            charge_array(translator, len(name))
    return features

def _train(translator, args):
    translator.allowed(args, {
        "classifier", "features", "classProperty", "inputProperties",
        "subsampling", "subsamplingSeed",
    })
    for required in ("classifier", "features", "classProperty"):
        if required not in args:
            fail(f"Classifier.train requires {required}")
    classifier = _supported(args["classifier"])
    class_property = args["classProperty"]
    if (not isinstance(class_property, str) or not class_property
            or "." in class_property):
        fail("Classifier classProperty must be a nonempty flat property name")
    charge_array(translator, len(class_property))
    schema = _input_properties(translator, args.get("inputProperties"))

    subsampling = args.get("subsampling", 1.0)
    if isinstance(subsampling, bool) or type(subsampling) not in (int, float):
        fail("Classifier.train only supports subsampling=1")
    if type(subsampling) is float and not math.isfinite(subsampling):
        fail("Classifier.train only supports subsampling=1")
    if subsampling != 1:
        fail("Classifier.train only supports subsampling=1")
    seed = integer(args.get("subsamplingSeed", 0), "Classifier subsamplingSeed")
    if seed != 0:
        fail("Classifier.train only supports subsamplingSeed=0")

    features = _features(translator, args["features"])
    dimension = len(schema)
    # Reserve the maximum bounded row, grouping and center work before any
    # training vectors, class accumulators or model tuples are materialized.
    charge_array(
        translator,
        len(features) * (3 * dimension + 3) + MAX_CLASSES * dimension,
    )
    sums = {}
    counts = {}
    rows = []
    for feature in features:
        properties = feature["properties"]
        if class_property not in properties:
            fail(f"Classifier feature is missing classProperty {class_property!r}")
        label = _label(properties[class_property])
        vector = []
        for name in schema:
            if name not in properties:
                fail(f"Classifier feature is missing input property {name!r}")
            vector.append(_number_fraction(properties[name], f"Classifier property {name!r}"))
        vector = tuple(vector)
        if label not in sums:
            sums[label] = [Fraction(0) for _ in range(dimension)]
            counts[label] = 0
        for axis, value in enumerate(vector):
            sums[label][axis] += value
        counts[label] += 1
        rows.append((label, vector))

    labels = tuple(sorted(sums))
    if len(labels) > MAX_CLASSES:
        fail(f"Classifier supports at most {MAX_CLASSES} classes")
    centers = tuple(
        tuple(total / counts[label] for total in sums[label])
        for label in labels
    )
    return StaticMinimumDistance(
        classifier.metric, classifier.k_nearest, classifier.output_mode,
        schema, labels, centers, tuple(rows),
    )

def _construct(translator, args):
    translator.allowed(args, {"metric", "kNearest"})
    metric = require_metric(args.get("metric", "euclidean"))
    k_nearest = integer(args.get("kNearest", 1), "Classifier kNearest", 1)
    if k_nearest != 1:
        fail("Only Classifier.minimumDistance kNearest=1 is supported")
    return StaticMinimumDistance(metric=metric)

def invoke_classifier(translator, name, args):
    """Evaluate the bounded minimum-distance classifier API surface."""
    if name not in CLASSIFIER_FUNCTIONS:
        fail(f"Unsupported Earth Engine algorithm: {name}")
    if name == "Classifier.minimumDistance":
        return _construct(translator, args)
    if name == "Classifier.train":
        return _train(translator, args)
    if name == "Classifier.schema":
        translator.allowed(args, {"classifier"})
        if "classifier" not in args:
            fail("Classifier.schema requires classifier")
        classifier = _supported(args["classifier"])
        if classifier.schema is None:
            charge_array(translator, 1)
            return None
        charge_array(translator, 1 + len(classifier.schema))
        return list(classifier.schema)
    translator.allowed(args, {"classifier", "mode"})
    if "classifier" not in args or "mode" not in args:
        fail("Classifier.setOutputMode requires classifier and mode")
    classifier = _supported(args["classifier"])
    if args["mode"] != "CLASSIFICATION":
        fail("Only CLASSIFICATION output mode is supported for minimum distance")
    return classifier

def predict_class(translator, classifier, values):
    """Return the unique nearest class label for one finite feature vector."""
    classifier = require_trained(classifier)
    if not isinstance(values, (list, tuple)) or len(values) != len(classifier.schema):
        fail("Classifier prediction vector must match the trained schema")
    charge_array(translator, len(values))
    vector = tuple(
        _number_fraction(value, "Classifier prediction value", allow_fraction=True)
        for value in values
    )
    return predict_unique(
        translator, classifier.metric, vector, classifier.labels, classifier.centers,
    )
