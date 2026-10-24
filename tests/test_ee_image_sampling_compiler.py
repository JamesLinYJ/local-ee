"""Compiler behavior for real, versioned Image.sample table producers."""
from copy import deepcopy
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.sampling_spec import decode_sampling_spec, sampling_columns
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
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["red", "nir", "extra"]}},
    }]
    items = {"sentinel-2-l2a": [
        {
            "id": item_id,
            "bbox": [0, 0, 2, 2],
            "geometry": GEOMETRY,
            "properties": {"system:index": item_id},
        }
        for item_id in ("training-scene", "target-scene")
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_ee(ee, value, local, options=None):
    return compile_expression(encode(ee, value), local[0], local[1], options=options)


def nodes_for(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def test_image_sample_compiles_to_opaque_v2_table_with_explicit_sampling(ee, local):
    region = ee.Geometry(GEOMETRY)
    table = ee.Image("training-scene").sample(
        region=region,
        scale=10,
        projection=ee.Projection("EPSG:32610"),
        factor=0.25,
        seed=13,
        dropNulls=False,
        geometries=True,
    )

    result = compile_ee(ee, table, local)

    assert result["kind"] == "sample_table"
    assert result["source_item_ids"] == ["training-scene"]
    assert result["grid_options"] == {"scale": 10, "crs": "EPSG:32610"}
    assert "value" not in result and "features" not in result and "rows" not in result
    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["version"] == 2
    assert spec["regions"]["features"] == [{
        "type": "Feature", "geometry": GEOMETRY, "properties": {},
    }]
    assert spec["bands"] == ["red", "nir", "extra"]
    assert spec["properties"] == []
    assert spec["geometries"] is True
    assert spec["image_sample"] == {
        "algorithm": "splitmix64-grid-v1",
        "factor": 0.25,
        "num_pixels": None,
        "seed": 13,
        "drop_nulls": False,
    }
    assert result["bands"] == sampling_columns(spec)
    sampler, = nodes_for(result, "local_ee_sample_regions")
    assert set(sampler["arguments"]) == {"data", "spec"}
    assert sampler["arguments"]["spec"] == result["sample_spec"]
    data_node = result["process_graph"][sampler["arguments"]["data"]["from_node"]]
    assert data_node["process_id"] == "resample_spatial"
    assert data_node["arguments"]["resolution"] == 10
    assert any("deterministic local grid hash" in warning
               for warning in result["warnings"])


def test_image_sample_defaults_to_finite_image_footprint_and_first_band_grid(ee, local):
    result = compile_ee(ee, ee.Image("training-scene").sample(), local)

    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["version"] == 2
    # Raw local catalog footprints use the legacy planar model. The footprint
    # union retains that model explicitly so a later typed-geometry consumer
    # does not reinterpret it as EE's default spherical geometry.
    assert spec["regions"]["features"][0]["geometry"] == {
        **GEOMETRY, "geodesic": False, "evenOdd": True,
    }
    assert spec["regions"]["features"][0]["properties"] == {}
    assert spec["grid"] == {"scale": None, "crs": None}
    assert spec["image_sample"] == {
        "algorithm": "splitmix64-grid-v1",
        "factor": None,
        "num_pixels": None,
        "seed": 0,
        "drop_nulls": True,
    }
    assert result["grid_options"] == {"scale": None, "crs": None}


def test_image_sample_num_pixels_zero_is_a_lazy_known_empty_table(ee, local):
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.ir import SampledFeatures
    from gee.compat.earthengine.sampled_feature_ops import sampled_table_known_empty

    expression = ee.Image("training-scene").sample(numPixels=0, dropNulls=False)
    translator = Translator(local[0], local[1], {})
    sampled = translator.evaluate(encode(ee, expression))

    assert isinstance(sampled, SampledFeatures)
    assert sampled_table_known_empty(sampled)
    result = compile_ee(ee, expression, local)
    assert result["kind"] == "sample_table"
    assert "rows" not in result and "features" not in result
    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["image_sample"]["num_pixels"] == 0
    sampler, = nodes_for(result, "local_ee_sample_regions")
    assert sampler["arguments"]["spec"] == result["sample_spec"]


def test_image_sample_filter_and_limit_preserve_the_v2_producer(ee, local):
    from gee.sample_table_spec import decode_sample_operation

    sampled = ee.Image("training-scene").sample(dropNulls=False)
    result = compile_ee(
        ee,
        sampled.filter(ee.Filter.notNull(["red", "nir"])).limit(10),
        local,
    )

    sampler, = nodes_for(result, "local_ee_sample_regions")
    operations = nodes_for(result, "local_ee_sample_table_op")
    assert decode_sampling_spec(sampler["arguments"]["spec"])["version"] == 2
    assert len(operations) == 2
    decoded = [decode_sample_operation(node["arguments"]["spec"])
               for node in operations]
    assert [operation["operation"] for operation in decoded] == ["filter", "limit"]
    assert decoded[1]["count"] == 10


@pytest.mark.parametrize("options,pattern", [
    ({"factor": 0}, "factor"),
    ({"numPixels": 1001}, "numPixels"),
    ({"factor": 0.5, "numPixels": 10}, "factor and numPixels"),
    ({"seed": 2**31}, "seed"),
    ({"tileScale": 2}, "tileScale=1"),
    ({"dropNulls": 1}, "dropNulls must be a boolean"),
    ({"geometries": 1}, "geometries must be a boolean"),
    ({"projection": "EPSG:32610"}, "projection requires"),
])
def test_image_sample_rejects_unsupported_or_invalid_parameters(ee, local, options, pattern):
    expression = ee.Image("training-scene").sample(**options)
    with pytest.raises(UnsupportedEEError, match=pattern):
        compile_ee(ee, expression, local)


def test_image_sample_rejects_unknown_serialized_parameters_and_unbound_default_roi(ee, local):
    encoded = deepcopy(encode(ee, ee.Image("training-scene").sample()))
    call = next(node for _, node in encoded.get("scope", [])
                if isinstance(node, dict)
                and node.get("functionName") == "Image.sample")
    call["arguments"]["unknown"] = True
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(encoded, local[0], local[1])

    no_source = ee.Image.constant(1).sample()
    with pytest.raises(UnsupportedEEError, match="finite image footprint"):
        compile_ee(ee, no_source, local)


def test_sample_band_metadata_is_static_and_explicit_rf_schema_uses_fixed_grid(ee, local):
    sampled = ee.Image("training-scene").sample(
        region=ee.Geometry(GEOMETRY), scale=10,
        projection=ee.Projection("EPSG:32610"),
    )
    band_order = compile_ee(ee, sampled.get("band_order"), local)
    property_names = compile_ee(ee, sampled.propertyNames(), local)
    assert band_order["kind"] == "value"
    assert band_order["value"] == ["red", "nir", "extra"]
    assert property_names["kind"] == "value"
    assert property_names["value"] == ["band_order"]

    model = ee.Classifier.smileRandomForest(numberOfTrees=2).train(
        features=sampled, classProperty="red", inputProperties=["nir"],
    )
    target = ee.Image("target-scene").select("nir").classify(model)
    result = compile_ee(
        ee, target, local,
        options={"scale": 30, "crs": "EPSG:32610", "region": GEOMETRY},
    )
    assert set(result["source_item_ids"]) == {"training-scene", "target-scene"}
    sampler, = nodes_for(result, "local_ee_sample_regions")
    spec = decode_sampling_spec(sampler["arguments"]["spec"])
    assert spec["grid"] == {"scale": 10, "crs": "EPSG:32610"}
    sample_data = result["process_graph"][sampler["arguments"]["data"]["from_node"]]
    assert sample_data["process_id"] == "resample_spatial"
    assert sample_data["arguments"]["resolution"] == 10
    assert sorted(node["arguments"]["resolution"]
                  for node in nodes_for(result, "resample_spatial")) == [10, 30]
    assert "region" not in sample_data["arguments"]


def test_classifier_train_uses_declared_sample_schema_and_keeps_model_opaque(ee, local):
    sampled = ee.Image("training-scene").sample()
    model = ee.Classifier.smileRandomForest(numberOfTrees=2).train(
        features=sampled, classProperty="red",
    )
    declared = compile_ee(ee, sampled.get("band_order"), local)["value"]
    assert declared == ["red", "nir", "extra"]
    assert compile_ee(ee, model.schema(), local)["value"] == declared
    with pytest.raises(UnsupportedEEError, match="public JSON|server-object JSON"):
        compile_ee(ee, model, local)
