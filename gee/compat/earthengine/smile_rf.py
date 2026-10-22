"""Pure IR construction for the pinned Smile RandomForest classifier path."""
from __future__ import annotations

from dataclasses import replace
import math

from ...smile_rf_spec import (
    prepare_rf_parameters,
    prepare_rf_spec,
    decode_rf_spec,
)
from .array_core import charge_array
from .ir import (
    DynamicMinimumDistance,
    SampledFeatures,
    SmileRandomForest,
    TrainedSmileRandomForest,
    fail,
    integer,
)
from .smile_rf_training import (
    literal_rows,
    validate_schema,
)


CLASSIFIER_FUNCTIONS = frozenset({
    "Classifier.smileRandomForest", "Classifier.train",
    "Classifier.schema", "Classifier.setOutputMode",
})


def _parameter_values(classifier):
    return {
        "number_of_trees": classifier.number_of_trees,
        "variables_per_split": classifier.variables_per_split,
        "min_leaf_population": classifier.min_leaf_population,
        "bag_fraction": classifier.bag_fraction,
        "max_nodes": classifier.max_nodes,
        "seed": classifier.seed,
    }


def _parameters(translator, arguments):
    translator.allowed(arguments, {
        "numberOfTrees", "variablesPerSplit", "minLeafPopulation",
        "bagFraction", "maxNodes", "seed",
    })
    if "numberOfTrees" not in arguments:
        fail("Classifier.smileRandomForest requires numberOfTrees")
    work = 1 + sum(len(key) for key in arguments)
    charge_array(translator, work)
    try:
        values = prepare_rf_parameters(
            arguments["numberOfTrees"],
            arguments.get("variablesPerSplit"),
            arguments.get("minLeafPopulation", 1),
            arguments.get("bagFraction", 0.5),
            arguments.get("maxNodes"),
            arguments.get("seed", 0),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        fail(str(exc))
    return SmileRandomForest(**values)


def _training_spec(translator, classifier, schema, class_property):
    charge_array(translator, 256 + len(class_property) * 6
                 + sum(len(name) * 6 for name in schema))
    try:
        text = prepare_rf_spec(_parameter_values(classifier), list(schema), class_property)
        decode_rf_spec(text)
        return text
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(str(exc))


def _train(translator, arguments):
    translator.allowed(arguments, {
        "classifier", "features", "classProperty", "inputProperties",
        "subsampling", "subsamplingSeed",
    })
    for required in ("classifier", "features", "classProperty", "inputProperties"):
        if required not in arguments:
            fail(f"Classifier.train requires {required}")
    classifier = arguments["classifier"]
    if not isinstance(classifier, SmileRandomForest):
        fail("Classifier.train requires an untrained ee.Classifier.smileRandomForest")
    if classifier.output_mode != "CLASSIFICATION":
        fail("Only CLASSIFICATION output mode is supported for Smile RandomForest")

    class_property = arguments["classProperty"]
    if (type(class_property) is not str or not class_property
            or "." in class_property or len(class_property) > 256):
        fail("Classifier classProperty must be a nonempty flat property name")
    charge_array(translator, len(class_property))
    schema = validate_schema(translator, arguments["inputProperties"])
    subsampling = arguments.get("subsampling", 1.0)
    if (isinstance(subsampling, bool) or type(subsampling) not in (int, float)
            or not math.isfinite(subsampling) or subsampling != 1):
        fail("Classifier.train only supports subsampling=1 for Smile RandomForest")
    seed = integer(arguments.get("subsamplingSeed", 0), "Classifier subsamplingSeed")
    if seed != 0:
        fail("Classifier.train only supports subsamplingSeed=0 for Smile RandomForest")

    try:
        training_spec = _training_spec(translator, classifier, schema, class_property)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(str(exc))

    features = arguments["features"]
    if isinstance(features, SampledFeatures):
        from .sampled_feature_ops import validated_sampled_schema

        try:
            sample_spec, columns, _ = validated_sampled_schema(
                features, translator, "Classifier.train sample table",
            )
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Classifier.train requires a valid server-side sample table: {exc}")
        charge_array(translator, len(training_spec))
        if not sample_spec["regions"]["features"]:
            fail("Classifier.train requires at least one sampling region")
        if class_property not in columns or not set(schema) <= set(columns):
            fail("Random forest training fields must exist in the sample table columns")
        return TrainedSmileRandomForest(
            classifier, schema, class_property, training_spec, samples=features,
        )

    if isinstance(features, DynamicMinimumDistance):
        fail("Smile RandomForest cannot be trained from a minimum-distance model")
    rows = literal_rows(translator, features, schema, class_property, training_spec)
    return TrainedSmileRandomForest(
        classifier, schema, class_property, training_spec, rows=rows,
    )


def invoke_classifier(translator, name, arguments):
    """Handle only the independent Smile RandomForest API type."""
    if name not in CLASSIFIER_FUNCTIONS:
        fail(f"Unsupported Earth Engine algorithm: {name}")
    if name == "Classifier.smileRandomForest":
        return _parameters(translator, arguments)
    if name == "Classifier.train":
        return _train(translator, arguments)
    if name == "Classifier.schema":
        translator.allowed(arguments, {"classifier"})
        if "classifier" not in arguments:
            fail("Classifier.schema requires classifier")
        classifier = arguments["classifier"]
        if isinstance(classifier, SmileRandomForest):
            charge_array(translator, 1)
            return None
        if isinstance(classifier, TrainedSmileRandomForest):
            charge_array(translator, 1 + len(classifier.schema)
                         + sum(map(len, classifier.schema)))
            return list(classifier.schema)
        fail("Classifier.schema requires a Smile RandomForest classifier")

    translator.allowed(arguments, {"classifier", "mode"})
    if "classifier" not in arguments or "mode" not in arguments:
        fail("Classifier.setOutputMode requires classifier and mode")
    if arguments["mode"] != "CLASSIFICATION":
        fail("Only CLASSIFICATION output mode is supported for Smile RandomForest")
    classifier = arguments["classifier"]
    if isinstance(classifier, SmileRandomForest):
        charge_array(translator, 2)
        return replace(classifier, output_mode="CLASSIFICATION")
    if isinstance(classifier, TrainedSmileRandomForest):
        charge_array(translator, 2 + sum(map(len, classifier.schema)))
        return replace(
            classifier,
            classifier=replace(classifier.classifier, output_mode="CLASSIFICATION"),
        )
    fail("Classifier.setOutputMode requires a Smile RandomForest classifier")
