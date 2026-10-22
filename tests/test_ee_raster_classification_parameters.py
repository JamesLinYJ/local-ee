"""Pinned SDK parameters, schema layout and pure raster-classifier graph IR."""
from fractions import Fraction
from pathlib import Path

import pytest

from gee.compat.earthengine.classifier_model import encode_model
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Collection, Image, Pixel, Source, UnsupportedEEError, rebind
from gee.compat.earthengine.minimum_distance import StaticMinimumDistance
from gee.compat.earthengine import raster_classification
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture
def local():
    names = ["blue", "red", "nir", "extra"]
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": names}},
    }]
    items = {"sentinel-2-l2a": [{
        "id": "scene-1",
        "bbox": [0, 0, 2, 2],
        "geometry": GEOMETRY,
        "properties": {
            "system:time_start": 1000,
            "system:index": "scene-1",
            "kept": "source property",
        },
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def find_invocation(expression, name="Image.classify"):
    candidates = [node for _, node in expression.get("scope", [])
                  if isinstance(node, dict) and node.get("functionName") == name]
    if expression.get("functionName") == name:
        candidates.append(expression)
    assert candidates, f"serialized expression has no {name} call"
    return candidates[-1]


def train(ee):
    features = ee.FeatureCollection([
        ee.Feature(None, {"red": 0, "nir": 0, "label": 1}),
        ee.Feature(None, {"red": 1, "nir": 2, "label": 5}),
    ])
    return ee.Classifier.minimumDistance(metric="euclidean").train(
        features=features,
        classProperty="label",
        inputProperties=["nir", "red"],
    )


def test_sdk_image_classify_compiles_one_named_exact_model_band_in_schema_order(ee, local):
    catalog, items = local
    source = ee.ImageCollection("sentinel-2-l2a").first()
    image = source.select(["blue", "red", "nir", "extra"]).toDouble()
    classified = image.classify(train(ee), outputName="landcover")
    result = compile_expression(encode(ee, classified), catalog, items)

    assert result["bands"] == ["landcover"]
    assert result["properties"] == items["sentinel-2-l2a"][0]["properties"]
    assert result["source_item_ids"] == ["scene-1"]
    graph = result["process_graph"]
    nodes = [node for node in graph.values()]
    classifier_nodes = [node for node in nodes
                        if node["process_id"] == "local_ee_minimum_distance"]
    assert len(classifier_nodes) == 1
    native = classifier_nodes[0]["arguments"]
    assert native["model"] == {
        "version": 1,
        "metric": "euclidean",
        "schema": ["nir", "red"],
        "labels": [1, 5],
        "centers": [[ ["0", "1"], ["0", "1"] ],
                    [ ["2", "1"], ["1", "1"] ]],
    }
    assert [node["arguments"]["target"] for node in nodes
            if node["process_id"] == "rename_labels"
            and node["arguments"].get("target") in (["nir"], ["red"])] == [
                ["nir"], ["red"],
            ]
    loads = [node for node in nodes if node["process_id"] == "load_collection"]
    assert len(loads) == 1
    assert loads[0]["arguments"]["bands"] == ["red", "nir"]
    # The selected Float64 bands reach the dedicated classifier process.
    assert any(node["process_id"] == "local_ee_to_double" for node in nodes)


@pytest.mark.parametrize("mutation", [
    lambda args: args.pop("image"),
    lambda args: args.pop("classifier"),
    lambda args: args.update(unexpected=1),
    lambda args: args.update(outputName=""),
    lambda args: args.update(outputName="bad.name"),
    lambda args: args.update(outputName=None),
    lambda args: args.update(outputName=3),
])
def test_sdk_image_classify_rejects_missing_unknown_and_invalid_parameters(
        ee, local, mutation):
    expression = encode(
        ee,
        ee.ImageCollection("sentinel-2-l2a").first().classify(train(ee)),
    )
    mutation(find_invocation(expression)["arguments"])
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, local[0], local[1])


def test_sdk_image_classify_rejects_missing_schema_band_and_untrained_model(ee, local):
    catalog, items = local
    missing_band = ee.ImageCollection("sentinel-2-l2a").first().select(["red"])
    with pytest.raises(UnsupportedEEError, match="missing classifier schema band"):
        compile_expression(encode(ee, missing_band.classify(train(ee))), catalog, items)

    untrained = ee.ImageCollection("sentinel-2-l2a").first().classify(
        ee.Classifier.minimumDistance(),
    )
    with pytest.raises(UnsupportedEEError, match="must be trained"):
        compile_expression(encode(ee, untrained), catalog, items)


def raw_classifier():
    return StaticMinimumDistance(
        metric="euclidean",
        schema=("nir", "red"),
        labels=(3,),
        centers=((Fraction(2), Fraction(1)),),
        training_rows=((3, (Fraction(2), Fraction(1))),),
    )


def test_direct_ir_ignores_extra_band_mask_and_preserves_image_metadata():
    source = Source("sentinel-2-l2a", ("scene-1",), ("red", "nir", "extra"))
    red = Pixel("band", (source, "red"))
    nir = Pixel("band", (source, "nir"))
    extra_masked = Pixel("is_nodata", (Pixel("band", (source, "extra")),), True)
    props = {"tag": "retained"}
    footprint = {"type": "Polygon", "coordinates": []}
    image = Image(
        [("extra", extra_masked), ("red", red), ("nir", nir)],
        props,
        source=source,
        mapped=True,
        inherit_props=False,
        copied_props=("tag",),
        footprint=footprint,
        footprint_is_absolute=True,
    )

    result = Translator([], {}, {}).invoke(
        "Image.classify", {"image": image, "classifier": raw_classifier()},
    )

    assert result.bands[0][0] == "classification"
    inputs, model = result.bands[0][1].args
    assert inputs == (nir, red)
    assert extra_masked not in inputs
    assert model == encode_model(raw_classifier())
    assert result.props is props
    assert result.source is source
    assert result.footprint is footprint
    assert (result.mapped, result.inherit_props, result.copied_props,
            result.footprint_is_absolute) == (True, False, ("tag",), True)

    rebound = rebind(Collection(source, result), ("scene-2",))
    rebound_inputs = rebound.image.bands[0][1].args[0]
    assert all(input_pixel.args[0].ids == ("scene-2",)
               for input_pixel in rebound_inputs)


def test_direct_ir_rejects_ambiguous_missing_wrong_typed_and_untrained_inputs():
    source = Source("sentinel-2-l2a", ("scene-1",), ("red", "nir"))
    red = Pixel("band", (source, "red"))
    nir = Pixel("band", (source, "nir"))
    model = raw_classifier()
    translator = Translator([], {}, {})
    cases = [
        ({"image": Image([("red", red)], {}), "classifier": model}, "missing classifier schema band"),
        ({"image": Image([("red", red), ("nir", nir), ("nir", red)], {}),
          "classifier": model}, "ambiguous"),
        ({"image": 1, "classifier": model}, "must be an Earth Engine Image"),
        ({"image": Image([("red", red), ("nir", nir)], {}), "classifier": 3},
         "Expected a supported"),
        ({"image": Image([("red", red), ("nir", nir)], {}),
          "classifier": StaticMinimumDistance(metric="euclidean")}, "must be trained"),
        ({"image": Image([("red", red), ("nir", nir)], {})}, "requires classifier"),
    ]
    for arguments, message in cases:
        with pytest.raises(UnsupportedEEError, match=message):
            translator.invoke("Image.classify", arguments)


def test_serialization_work_is_charged_before_model_encoding(monkeypatch):
    source = Source("sentinel-2-l2a", ("scene-1",), ("red", "nir"))
    image = Image([
        ("red", Pixel("band", (source, "red"))),
        ("nir", Pixel("band", (source, "nir"))),
    ], {})
    translator = Translator([], {}, {})
    translator.steps = 49_999
    monkeypatch.setattr(
        raster_classification, "encode_model",
        lambda _classifier: pytest.fail("model encoding ran before the work charge"),
    )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        translator.invoke("Image.classify", {"image": image, "classifier": raw_classifier()})
    assert translator.steps == 49_999
