"""Bounded FeatureCollection rows and trained-model validation for Smile RF."""
from __future__ import annotations

from ...smile_rf_spec import (
    MAX_TRAINING_MAGNITUDE,
    decode_rf_rows,
    decode_rf_spec,
    prepare_rf_rows,
    prepare_rf_spec,
)
from .array_core import charge_array
from .feature_values import is_collection, validate_feature
from .ir import (
    SampledFeatures,
    SmileRandomForest,
    TrainedSmileRandomForest,
    fail,
)


MAX_TRAINING_FEATURES = 1_000
MAX_INPUT_PROPERTIES = 8
MAX_CLASSES = 64
MAX_EXACT_INTEGER = 2**53
MAX_ROWS_BYTES = 1_000_000


def validate_schema(translator, value):
    if (type(value) is not list or not 1 <= len(value) <= MAX_INPUT_PROPERTIES
            or any(type(name) is not str or not name or "." in name
                   or len(name) > 256 for name in value)
            or len(set(value)) != len(value)):
        fail(f"Classifier.train requires 1..{MAX_INPUT_PROPERTIES} unique flat inputProperties")
    charge_array(translator, len(value) + sum(map(len, value)))
    return tuple(value)


def _class_label(value):
    if isinstance(value, bool) or type(value) not in (int, float):
        fail("Random forest class labels must be integer values from 0 through 63")
    if type(value) is float and (not value.is_integer()):
        fail("Random forest class labels must be integer values from 0 through 63")
    if not 0 <= value < MAX_CLASSES:
        fail("Random forest class labels must be integer values from 0 through 63")
    return int(value)


def _numeric_feature(value, property_name):
    if type(value) is int:
        valid = abs(value) <= MAX_EXACT_INTEGER
    elif type(value) is float:
        valid = (value == value and abs(value) <= MAX_TRAINING_MAGNITUDE)
    else:
        valid = False
    if not valid:
        fail(f"Random forest input property {property_name!r} must be finite numeric data")
    return value


def literal_rows(translator, features, schema, class_property, spec_text):
    if not is_collection(features) or type(features.get("features")) is not list:
        fail("Classifier.train requires an inline FeatureCollection or Image.sampleRegions output")
    feature_rows = features["features"]
    if not 2 <= len(feature_rows) <= MAX_TRAINING_FEATURES:
        fail("Random forest training requires 2..1000 inline Features")
    # The values and row shape have strict count/precision bounds. Reserve a
    # safe wire size plus extraction/copy work before duplicating training rows.
    row_count = len(feature_rows)
    dimensions = len(schema)
    wire_bound = 32 + row_count * (10 + dimensions * 25)
    if wire_bound > MAX_ROWS_BYTES:
        fail("Random forest rows exceed the 1000000-byte wire budget")
    charge_array(translator, row_count * (2 * dimensions + 5)
                 + sum(map(len, schema)) + len(class_property))
    rows = []
    for feature in feature_rows:
        checked = validate_feature(translator, feature)
        properties = checked["properties"]
        if class_property not in properties:
            fail(f"Classifier feature is missing classProperty {class_property!r}")
        label = _class_label(properties[class_property])
        vector = []
        for name in schema:
            if name not in properties:
                fail(f"Classifier feature is missing input property {name!r}")
            vector.append(_numeric_feature(properties[name], name))
        rows.append([label, vector])
    try:
        text = prepare_rf_rows(rows, decode_rf_spec(spec_text))
        if len(text.encode("utf-8")) > MAX_ROWS_BYTES:
            fail("Random forest rows exceed the 1000000-byte wire budget")
        return text
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(str(exc))


def _parameter_values(classifier):
    return {
        "number_of_trees": classifier.number_of_trees,
        "variables_per_split": classifier.variables_per_split,
        "min_leaf_population": classifier.min_leaf_population,
        "bag_fraction": classifier.bag_fraction,
        "max_nodes": classifier.max_nodes,
        "seed": classifier.seed,
    }


def validate_trained_classifier(translator, classifier):
    """Revalidate an RF training IR before it becomes a raster Pixel."""
    if not isinstance(classifier, TrainedSmileRandomForest):
        fail("Image.classify requires a trained Smile RandomForest classifier")
    model = classifier.classifier
    if (not isinstance(model, SmileRandomForest)
            or model.output_mode != "CLASSIFICATION"
            or type(classifier.schema) is not tuple
            or not 1 <= len(classifier.schema) <= MAX_INPUT_PROPERTIES
            or any(type(name) is not str or not name or "." in name
                   or len(name) > 256 for name in classifier.schema)
            or len(set(classifier.schema)) != len(classifier.schema)
            or type(classifier.class_property) is not str
            or not classifier.class_property or "." in classifier.class_property
            or len(classifier.class_property) > 256
            or type(classifier.training_spec) is not str
            or (classifier.rows is not None and type(classifier.rows) is not str)
            or (classifier.samples is not None
                and (not isinstance(classifier.samples, SampledFeatures)
                     or type(classifier.samples.spec) is not str))
            or (classifier.rows is None) == (classifier.samples is None)):
        fail("Image.classify requires a valid trained Smile RandomForest classifier")

    sample_bytes = (len(classifier.samples.spec.encode("utf-8"))
                    if classifier.samples is not None else 0)
    work = (6 * (len(classifier.training_spec) + len(classifier.rows or ""))
            + 256 + sum(map(len, classifier.schema))
            + len(classifier.class_property) + 2 * sample_bytes)
    charge_array(translator, work)
    try:
        expected_spec = prepare_rf_spec(
            _parameter_values(model), list(classifier.schema), classifier.class_property,
        )
        spec = decode_rf_spec(classifier.training_spec)
        if expected_spec != classifier.training_spec:
            fail("Smile RandomForest training IR does not match its canonical specification")
        if classifier.rows is not None:
            decoded = decode_rf_rows(classifier.rows, spec)
            if prepare_rf_rows(decoded["rows"], spec) != classifier.rows:
                fail("Smile RandomForest literal rows must be canonical JSON")
        else:
            sampled = classifier.samples
            if not isinstance(sampled, SampledFeatures):
                fail("Smile RandomForest sample training IR is malformed")
            from .sampled_feature_ops import validated_sampled_schema

            sample_spec, columns, _ = validated_sampled_schema(
                sampled, translator, "Smile RandomForest training sample table",
            )
            if (not sample_spec["regions"]["features"]
                    or classifier.class_property not in columns
                    or not set(classifier.schema) <= set(columns)):
                fail("Smile RandomForest sample table does not contain its training schema")
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Invalid Smile RandomForest training IR: {exc}")
    return classifier
