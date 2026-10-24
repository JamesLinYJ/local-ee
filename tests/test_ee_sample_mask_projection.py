"""Official-wire compiler coverage for sampling direct fractional-mask bands."""
from __future__ import annotations

from pathlib import Path
import json

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.sample_mask_projection import project_sample_mask_image
from gee.compat.earthengine.sampled_training import image_node_estimate
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.sampling_spec import decode_sampling_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXTENT = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture(scope="module")
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture
def local():
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["red", "nir", "extra"]}},
    }]
    return catalog, {"sentinel-2-l2a": [
        {
            "id": item_id, "bbox": [0, 0, 2, 2], "geometry": EXTENT,
            "properties": {"system:index": item_id, "kind": "sample"},
        }
        for item_id in ("training-scene", "target-scene", "mask-scene")
    ]}


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def regions(ee, properties=None):
    properties = {} if properties is None else properties
    return ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), properties),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), properties),
    ])


def planar_roi(ee):
    return ee.Geometry(EXTENT, proj="EPSG:4326", geodesic=False)


def process_nodes(result, process_id):
    return [(key, node) for key, node in result["process_graph"].items()
            if node["process_id"] == process_id]


def apply_specs(result):
    return [
        json.loads(node["arguments"]["spec"])
        for node in result["process_graph"].values()
        if node["process_id"] == "local_ee_mask_weights"
    ]


def test_image_sample_v2_preserves_drop_nulls_false_and_projects_zero_as_nodata(ee, local):
    image = ee.Image("training-scene").select(["red", "nir"]).toDouble().updateMask(0.25)
    result = compile_expression(
        encode(ee, image.sample(region=ee.Geometry(EXTENT), dropNulls=False)),
        local[0], local[1],
    )

    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["version"] == 2
    assert spec["image_sample"]["drop_nulls"] is False
    assert spec["bands"] == ["red", "nir"]
    assert process_nodes(result, "local_ee_sample_regions")
    assert any(spec["op"] == "apply" for spec in apply_specs(result))
    assert "multiply" not in [
        node["process_id"] for node in result["process_graph"].values()
    ]


def test_sample_regions_projects_only_the_direct_carrier_and_keeps_v1_contract(ee, local):
    image = ee.Image("training-scene").select(["red", "nir"]).updateMask(0.25)
    expression = image.sampleRegions(
        collection=regions(ee, {"label": 1}), properties=["label"],
        geometries=False,
    )
    result = compile_expression(encode(ee, expression), local[0], local[1])

    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["version"] == 1
    assert spec["bands"] == ["red", "nir"]
    assert "image_sample" not in spec
    assert any(spec["op"] == "apply" for spec in apply_specs(result))
    assert len(process_nodes(result, "local_ee_sample_regions")) == 1

    translator = Translator(local[0], local[1], {})
    sampled = translator.evaluate(encode(ee, expression))
    projected = project_sample_mask_image(sampled.image, translator)
    assert len(result["process_graph"]) <= image_node_estimate(projected) + 1


@pytest.mark.parametrize("sampling_api", ["sample", "sampleRegions"])
def test_source_free_raw_constant_cannot_borrow_mask_raster_grid(ee, local, sampling_api):
    image = ee.Image.constant(1).updateMask(
        ee.Image("mask-scene").select("nir").multiply(0.1)
    )
    if sampling_api == "sample":
        expression = image.sample(region=planar_roi(ee), dropNulls=False)
    else:
        expression = image.sampleRegions(
            collection=regions(ee), geometries=False,
        )

    with pytest.raises(UnsupportedEEError, match="source-backed raw pixel values"):
        compile_expression(encode(ee, expression), local[0], local[1])


def test_source_image_cannot_hide_a_source_free_weighted_addbands_value(ee, local):
    mask = ee.Image("mask-scene").select("nir").multiply(0.1)
    unsupported_band = ee.Image.constant(1).updateMask(mask).rename("class")
    image = ee.Image("training-scene").select("red").addBands(unsupported_band)

    with pytest.raises(UnsupportedEEError, match="source-backed raw pixel values"):
        compile_expression(
            encode(ee, image.sample(region=planar_roi(ee))),
            local[0], local[1],
        )


def test_finite_on_grid_constant_raw_values_remain_sampleable(ee, local):
    weighted_destination = ee.Image("training-scene").select("red").updateMask(0.5)
    with_class = weighted_destination.addBands(
        ee.Image.constant(1).rename("class")
    )
    image = with_class.updateMask(0.25)
    result = compile_expression(
        encode(ee, image.sample(region=planar_roi(ee), dropNulls=False)),
        local[0], local[1],
    )

    assert result["kind"] == "sample_table"
    assert any(spec["op"] == "apply" for spec in apply_specs(result))
    assert any(node["process_id"] == "local_ee_constant_on_grid"
               for node in result["process_graph"].values())


def test_weighted_science_and_constant_class_band_reach_minimum_distance_training(ee, local):
    science = ee.Image("training-scene").select(["red", "nir"]).toDouble()
    weighted = science.updateMask(0.5)
    training = weighted.addBands(ee.Image.constant(1).rename("class"))
    samples = training.sampleRegions(
        collection=regions(ee), geometries=False,
    )
    classifier = ee.Classifier.minimumDistance(metric="euclidean").train(
        features=samples, classProperty="class", inputProperties=["red", "nir"],
    )
    result = compile_expression(
        encode(ee, ee.Image("target-scene").select(["red", "nir"]).classify(classifier)),
        local[0], local[1],
    )

    sample_nodes = process_nodes(result, "local_ee_sample_regions")
    trainer_nodes = process_nodes(result, "local_ee_train_minimum_distance")
    assert len(sample_nodes) == len(trainer_nodes) == 1
    assert decode_sampling_spec(sample_nodes[0][1]["arguments"]["spec"])["bands"] == [
        "red", "nir", "class",
    ]
    assert any(spec["op"] == "apply" for spec in apply_specs(result))
    assert set(result["source_item_ids"]) == {"training-scene", "target-scene"}


def test_weighted_science_and_constant_class_band_reach_smile_training(ee, local):
    weighted = ee.Image("training-scene").select(["red", "nir"]).updateMask(0.5)
    training = weighted.addBands(ee.Image.constant(0).rename("class"))
    samples = training.sampleRegions(collection=regions(ee), geometries=False)
    classifier = ee.Classifier.smileRandomForest(numberOfTrees=2).train(
        features=samples, classProperty="class", inputProperties=["red", "nir"],
    )
    result = compile_expression(
        encode(ee, ee.Image("target-scene").select(["red", "nir"]).classify(classifier)),
        local[0], local[1],
    )

    sample_nodes = process_nodes(result, "local_ee_sample_regions")
    trainer_nodes = process_nodes(result, "local_ee_train_smile_rf_samples")
    assert len(sample_nodes) == len(trainer_nodes) == 1
    assert decode_sampling_spec(sample_nodes[0][1]["arguments"]["spec"])["bands"] == [
        "red", "nir", "class",
    ]
    assert any(spec["op"] == "apply" for spec in apply_specs(result))
    assert set(result["source_item_ids"]) == {"training-scene", "target-scene"}


def test_sampled_error_matrix_lowering_projects_the_same_direct_carrier(ee, local):
    image = ee.Image("training-scene").select("red").updateMask(0.5)
    samples = image.sampleRegions(
        collection=regions(ee, {"actual": 1, "predicted": 1}),
        properties=["actual", "predicted"], geometries=False,
    )
    result = compile_expression(
        encode(ee, samples.errorMatrix("actual", "predicted", [1]).accuracy()),
        local[0], local[1],
    )

    assert len(process_nodes(result, "local_ee_sample_regions")) == 1
    assert len(process_nodes(result, "local_ee_error_matrix")) == 1
    assert any(spec["op"] == "apply" for spec in apply_specs(result))


@pytest.mark.parametrize("consumer", ["arithmetic", "clip", "where"])
def test_nested_weighted_carriers_remain_rejected(ee, local, consumer):
    weighted = ee.Image("training-scene").select("red").updateMask(0.5)
    if consumer == "arithmetic":
        image = weighted.multiply(2)
    elif consumer == "clip":
        image = weighted.clip(ee.Geometry(EXTENT))
    else:
        image = weighted.where(ee.Image.constant(0), 2)

    with pytest.raises(UnsupportedEEError, match="Fractional image masks require a mask-aware consumer"):
        compile_expression(encode(ee, image.sample()), local[0], local[1])


def test_mask_projection_rejects_unaligned_actual_source_lineages(ee, local):
    catalog, items = local
    for item in items["sentinel-2-l2a"]:
        item["properties"].update({
            "proj:code": "EPSG:32610",
            "proj:transform": [10, 0, 500000, 0, -10, 3000000],
        })
    items["sentinel-2-l2a"][2]["properties"]["proj:transform"][2] += 5
    mask = ee.Image("mask-scene").select("nir").multiply(0.5)
    weighted = ee.Image("training-scene").select("red").updateMask(mask)

    with pytest.raises(UnsupportedEEError, match="proven common pixel grid"):
        compile_expression(
            encode(ee, weighted.sample(region=ee.Geometry(EXTENT))),
            catalog, items,
        )


def test_projection_is_fresh_precharged_and_keeps_original_weight_identity():
    source = Source("sentinel-2-l2a", ("training-scene",), ("red",))
    raw, weight = Pixel("band", (source, "red")), const(0.25)
    carrier = Pixel("with_mask", (raw, weight))
    original = Image([("red", carrier)], {"kind": "training"})
    translator = Translator([], {}, {})

    first = project_sample_mask_image(original, translator)
    second = project_sample_mask_image(original, translator)

    assert first is not original and second is not original and first is not second
    assert first.bands is not original.bands and second.bands is not first.bands
    assert original.bands == [("red", carrier)]
    assert first.bands[0][1].op == "mask_apply"
    assert first.bands[0][1].args is carrier.args
    assert first.bands[0][1].args[1] is weight
    assert second.bands[0][1] is not first.bands[0][1]
    assert translator.steps > 0


def test_projection_work_is_precharged_before_copy_and_evaluator_depth_stays_bounded(ee, local):
    source = Source("sentinel-2-l2a", ("training-scene",), ("red",))
    carrier = Pixel("with_mask", (Pixel("band", (source, "red")), const(0.5)))
    image = Image([("red", carrier)], {})
    probe = Translator([], {}, {})
    project_sample_mask_image(image, probe)
    projection_copy_work = 8 + 4 + len("red") + 3
    lineage_work = probe.steps - projection_copy_work
    assert lineage_work > 0

    translator = Translator([], {}, {})
    translator.steps = 50_000 - lineage_work - projection_copy_work + 1
    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        project_sample_mask_image(image, translator)
    assert translator.steps == 50_000 - projection_copy_work + 1
    assert image.bands == [("red", carrier)]

    deep = ee.Image("training-scene")
    for _ in range(110):
        deep = deep.toFloat()
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compile_expression(
            encode(ee, deep.updateMask(0.5).sample(region=ee.Geometry(EXTENT))),
            local[0], local[1],
        )
