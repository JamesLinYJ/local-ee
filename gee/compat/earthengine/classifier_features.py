"""FeatureCollection adapters for the bounded static minimum-distance model."""
from __future__ import annotations

import numpy as np

from ...rf_validation_spec import (
    prepare_classify_spec,
    prepare_feature_rows,
    prepare_query_rows,
)
from ...sampling_spec import decode_sampling_spec, sampling_columns
from ...table_values import columns as table_columns
from .array_core import wrap_array
from .confusion_values import MAX_CONFUSION_CELLS, MAX_CONFUSION_CLASSES, make_confusion
from .feature_values import charge, is_collection, property_name, validate_feature
from .ir import DynamicMinimumDistance, SampledFeatures, fail
from .minimum_distance import predict_class, require_trained
from .runtime_feature_ir import RFClassifiedFeatureTable, RuntimeRFTrainingConfusion
from .smile_rf_training import validate_trained_classifier


_MAX_FEATURES = 1000


def _schema(translator, classifier):
    schema = classifier.schema
    if not isinstance(schema, tuple) or not schema:
        fail("Classifier must be trained with a nonempty flat input schema")
    charge(translator, len(schema))
    for name in schema:
        property_name(name)
        if not name or "." in name:
            fail("Classifier requires nonempty flat input property names")
        charge(translator, len(name))
    return schema


def _features(translator, value):
    if not is_collection(value):
        fail("Classifier feature operations require an inline FeatureCollection")
    features = value.get("features")
    if not isinstance(features, list):
        fail("Inline FeatureCollection requires a feature list")
    if len(features) > _MAX_FEATURES:
        fail("Classifier feature operations support at most 1000 features")
    charge(translator)
    for feature in features:
        charge(translator)
        validate_feature(translator, feature)
    return features


def _classify_features(translator, arguments):
    a = arguments
    translator.allowed(a, {"features", "classifier", "outputName"})
    if "features" not in a or "classifier" not in a:
        fail("FeatureCollection.classify requires features and classifier")

    from .ir import TrainedSmileRandomForest

    if isinstance(a["classifier"], TrainedSmileRandomForest):
        return _classify_rf_features(translator, a)

    if isinstance(a["classifier"], DynamicMinimumDistance):
        fail("FeatureCollection.classify does not support sample-trained classifiers")
    if isinstance(a["features"], SampledFeatures):
        fail("Sampled FeatureCollections support Classifier.train only")

    classifier = require_trained(a["classifier"])
    schema = _schema(translator, classifier)
    output_name = property_name(a.get("outputName", "classification"))
    if not output_name or "." in output_name:
        fail("FeatureCollection.classify outputName must be a nonempty flat property name")
    charge(translator, len(output_name))

    features = _features(translator, a["features"])
    # The predictions list contains one output label per input feature.
    charge(translator, len(features))
    predictions = []
    output_work = 0
    for feature in features:
        properties = feature["properties"]
        # validate_feature checked every key; charge the subsequent key scan,
        # including key lengths, and the output dictionary copy before work.
        charge(translator, len(properties))
        for key in properties:
            charge(translator, len(key))
        if output_name in properties:
            fail(f"FeatureCollection.classify output property already exists: {output_name}")

        charge(translator, len(schema))
        values = []
        for name in schema:
            if name not in properties:
                fail(f"FeatureCollection.classify is missing classifier property: {name}")
            if properties[name] is None:
                fail(f"FeatureCollection.classify classifier property is null: {name}")
            values.append(properties[name])
        predictions.append(predict_class(translator, classifier, values))
        output_work += len(feature) + len(properties) + 2

    # Preflight copies/label insertion for every output feature before creating
    # the result collection. All feature and prediction validation is complete.
    charge(translator, output_work + 1)
    return {
        "type": "FeatureCollection",
        "features": [
            {**feature, "properties": {**feature["properties"], output_name: label}}
            for feature, label in zip(features, predictions)
        ],
    }


def _classify_rf_features(translator, arguments):
    """Build a lazy FeatureCollection.classify node without predicting rows."""
    from .ir import TrainedSmileRandomForest

    source = arguments["features"]
    classifier = arguments["classifier"]
    if not isinstance(classifier, TrainedSmileRandomForest):
        fail("FeatureCollection.classify requires a trained Smile RandomForest")
    classifier = validate_trained_classifier(translator, classifier)
    schema = classifier.schema
    rows = None

    if isinstance(source, SampledFeatures):
        try:
            sample_spec = decode_sampling_spec(source.spec)
            original_columns = sampling_columns(sample_spec)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"FeatureCollection.classify has an invalid sample table: {exc}")
        row_count = 0 if not sample_spec["regions"]["features"] else None
    else:
        features = _features(translator, source)
        try:
            original_columns = table_columns(source)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"FeatureCollection.classify requires a bounded GeoJSON table: {exc}")
        row_count = len(features)
        charge(translator, row_count * (len(schema) + 1))
        query_rows = []
        for feature in features:
            properties = feature["properties"]
            values = []
            for name in schema:
                if name not in properties:
                    fail(f"FeatureCollection.classify is missing classifier property: {name}")
                if properties[name] is None:
                    fail(f"FeatureCollection.classify classifier property is null: {name}")
                values.append(properties[name])
            query_rows.append(values)
        try:
            prepare_query_rows(query_rows, len(schema))
            rows = prepare_feature_rows(source)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"FeatureCollection.classify rows are invalid: {exc}")

    output_name = property_name(arguments.get("outputName", "classification"))
    if not output_name or "." in output_name:
        fail("FeatureCollection.classify outputName must be a nonempty flat property name")
    if output_name in original_columns:
        fail(f"FeatureCollection.classify output property already exists: {output_name}")
    if row_count != 0 and not set(schema) <= set(original_columns):
        fail("FeatureCollection.classify table does not contain the classifier schema")
    output_columns = list(original_columns)
    output_columns.insert(len(output_columns) - 1, output_name)
    try:
        spec = prepare_classify_spec(output_name, output_columns)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"FeatureCollection.classify specification is invalid: {exc}")
    charge(translator, len(output_name) + len(spec) + len(output_columns))
    return RFClassifiedFeatureTable(
        source=source,
        classifier=classifier,
        spec=spec,
        columns=tuple(output_columns),
        row_count=row_count,
        rows=rows,
    )


def _classifier_confusion_matrix(translator, arguments):
    a = arguments
    translator.allowed(a, {"classifier"})
    if "classifier" not in a:
        fail("Classifier.confusionMatrix requires classifier")
    from .ir import TrainedSmileRandomForest
    if isinstance(a["classifier"], TrainedSmileRandomForest):
        classifier = validate_trained_classifier(translator, a["classifier"])
        return RuntimeRFTrainingConfusion(classifier)
    if isinstance(a["classifier"], DynamicMinimumDistance):
        fail("Classifier.confusionMatrix is unsupported for sample-trained classifiers")
    classifier = require_trained(a["classifier"])
    labels = classifier.labels
    if not isinstance(labels, tuple) or not labels or len(labels) > MAX_CONFUSION_CLASSES:
        fail("Classifier.confusionMatrix requires trained labels in 0..63")
    charge(translator, len(labels))
    if any(type(label) is not int or not 0 <= label < MAX_CONFUSION_CLASSES
           for label in labels):
        fail("Classifier.confusionMatrix requires trained labels in 0..63")
    label_set = set(labels)
    if len(label_set) != len(labels):
        fail("Classifier.confusionMatrix requires unique trained labels")

    dimension = max(labels) + 1
    cells = dimension * dimension
    if dimension > MAX_CONFUSION_CLASSES or cells > MAX_CONFUSION_CELLS:
        fail("Classifier.confusionMatrix exceeds 64 classes or 4096 cells")
    rows = classifier.training_rows
    if not isinstance(rows, tuple) or len(rows) > _MAX_FEATURES:
        fail("Classifier.confusionMatrix requires at most 1000 retained training rows")

    pairs = []
    for actual, values in rows:
        charge(translator)
        if type(actual) is not int or actual not in label_set:
            fail("Classifier.confusionMatrix training row has an unknown class label")
        predicted = predict_class(translator, classifier, values)
        pairs.append((actual, predicted))

    # Charge order construction, output cells, the wrap copy, and count pass
    # before matrix allocation. make_confusion performs one further charged
    # scan and copy; check that future cost against the shared limit now.
    charge(translator, dimension + 2 * cells + len(pairs))
    if translator.steps + cells + dimension > 50_000:
        fail("Earth Engine graph exceeds compilation limits")

    order = list(range(dimension))
    matrix = np.zeros((dimension, dimension), dtype=np.int64)
    for actual, predicted in pairs:
        matrix[actual, predicted] += 1
    return make_confusion(translator, wrap_array(matrix), order=order)


def invoke_classifier_features(translator, name, arguments):
    """Evaluate only inline FeatureCollection.classify and trained confusionMatrix."""
    if name == "FeatureCollection.classify":
        return _classify_features(translator, arguments)
    if name == "Classifier.confusionMatrix":
        return _classifier_confusion_matrix(translator, arguments)
    fail(f"Unsupported classifier feature algorithm: {name}")
