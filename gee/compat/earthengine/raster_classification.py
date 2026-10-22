"""Image.classify parameter validation and model-to-pixel lowering."""
from __future__ import annotations

from dataclasses import replace

from .classifier_model import encode_model, model_serialization_work
from .ir import (
    DynamicMinimumDistance,
    Image,
    Pixel,
    SmileRandomForest,
    SampledFeatures,
    TrainedSmileRandomForest,
    fail,
)
from .minimum_distance_metrics import require_metric


MAX_IMAGE_BANDS = 10_000
MAX_TRANSLATOR_WORK = 50_000


def _charge(translator, work):
    if work < 0 or work > MAX_TRANSLATOR_WORK or translator.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.classify exceeds the 50000-step compilation work budget")
    translator.steps += work


def invoke_image_classify(translator, arguments):
    """Validate Image.classify and build an exact model-backed Pixel node."""
    allowed = {"image", "classifier", "outputName"}
    translator.allowed(arguments, allowed)
    for required in ("image", "classifier"):
        if required not in arguments:
            fail(f"Image.classify requires {required}")

    image = arguments["image"]
    if not isinstance(image, Image):
        fail("Image.classify image must be an Earth Engine Image")
    output_name = arguments.get("outputName", "classification")
    if type(output_name) is not str or not output_name or "." in output_name:
        fail("Image.classify outputName must be a nonempty flat band name")

    classifier = arguments["classifier"]
    if isinstance(classifier, SmileRandomForest):
        fail("Image.classify requires a trained Smile RandomForest classifier")
    from .smile_rf_training import validate_trained_classifier

    smile_rf = isinstance(classifier, TrainedSmileRandomForest)
    if smile_rf:
        validate_trained_classifier(translator, classifier)
    dynamic = isinstance(classifier, DynamicMinimumDistance)
    if smile_rf:
        schema = classifier.schema
        serialization_work = 0  # validate_trained_classifier charged the full wire first.
    elif dynamic:
        require_metric(classifier.metric)
        schema = classifier.schema
        if (not isinstance(classifier.samples, SampledFeatures)
                or type(classifier.samples.spec) is not str
                or type(schema) is not tuple or not 1 <= len(schema) <= 8
                or any(type(name) is not str or not name or "." in name for name in schema)
                or len(set(schema)) != len(schema)
                or type(classifier.class_property) is not str
                or not classifier.class_property or "." in classifier.class_property
                or classifier.output_mode != "CLASSIFICATION"):
            fail("Image.classify requires a valid sample-trained minimum-distance classifier")
        serialization_work = (len(classifier.samples.spec)
                              + len(classifier.class_property)
                              + sum(map(len, schema)) + 8)
    else:
        serialization_work = model_serialization_work(classifier)
        schema = classifier.schema
    bands = image.bands
    if type(bands) is not list or len(bands) > MAX_IMAGE_BANDS:
        fail("Image.classify input must have at most 10000 named bands")

    name_work = 0
    for band in bands:
        if (type(band) is not tuple or len(band) != 2 or type(band[0]) is not str
                or not isinstance(band[1], Pixel)):
            fail("Image.classify requires named scalar pixel bands")
        name_work += len(band[0])

    # Pay for model serialization/spec, band-name indexing, schema lookup and
    # the replacement IR before allocating the wire object or input layout.
    work = (serialization_work + len(bands) * 2 + name_work
            + len(schema) * 3 + sum(map(len, schema))
            + len(output_name) + 4)
    _charge(translator, work)

    selected_names = set(schema)
    found = {}
    ambiguous = set()
    for name, pixel in bands:
        if name not in selected_names:
            continue
        if name in found:
            ambiguous.add(name)
        else:
            found[name] = pixel
    for name in schema:
        if name in ambiguous:
            fail(f"Image.classify input band name is ambiguous: {name!r}")
        if name not in found:
            fail(f"Image.classify is missing classifier schema band: {name!r}")

    inputs = tuple(found[name] for name in schema)
    if smile_rf:
        classified = Pixel("smile_rf_classify", (inputs, classifier))
    elif dynamic:
        classified = Pixel("trained_classify", (inputs, classifier))
    else:
        model = encode_model(classifier)
        classified = Pixel("classify", (inputs, model))
    return replace(image, bands=[(output_name, classified)])
