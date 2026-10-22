"""Official Python SDK serialization and compiler paths for Image.sampleRegions."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
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
            "id": "training-scene", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
            "properties": {"system:index": "training-scene", "kind": "training"},
        },
        {
            "id": "target-a", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
            "properties": {"system:index": "target-a", "kind": "target"},
        },
        {
            "id": "target-b", "bbox": [0, 0, 2, 2], "geometry": GEOMETRY,
            "properties": {"system:index": "target-b", "kind": "target"},
        },
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def training_regions(ee):
    return ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([0.5, 0.5]), {"label": 2, "unused": "x"}),
        ee.Feature(ee.Geometry.Point([1.5, 1.5]), {"label": 7, "unused": "y"}),
    ])


def sample_image(ee):
    return ee.Image("training-scene")


def sample(ee, **kwargs):
    arguments = {
        "collection": training_regions(ee), "properties": ["label"],
        "geometries": True, "scale": 10,
        "projection": ee.Projection("EPSG:32610"),
    }
    arguments.update(kwargs)
    return sample_image(ee).sampleRegions(**arguments)


def nodes_for(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def test_sample_regions_compiles_to_a_lazy_bounded_sample_table(ee, local):
    result = compile_expression(encode(ee, sample(ee)), local[0], local[1])

    assert result["kind"] == "sample_table"
    assert result["source_item_ids"] == ["training-scene"]
    assert result["grid_options"] == {"scale": 10, "crs": "EPSG:32610"}
    assert "value" not in result and "features" not in result and "rows" not in result
    spec = decode_sampling_spec(result["sample_spec"])
    assert spec["bands"] == ["red", "nir", "extra"]
    assert spec["properties"] == ["label"]
    assert result["bands"] == sampling_columns(spec)
    sampler, = nodes_for(result, "local_ee_sample_regions")
    assert set(sampler["arguments"]) == {"data", "spec"}
    assert sampler["arguments"]["spec"] == result["sample_spec"]
    assert result["process_graph"][next(reversed(result["process_graph"]))]["result"] is True
    assert any(node["process_id"] == "resample_spatial"
               and node["arguments"].get("resolution") == 10
               for node in result["process_graph"].values())
    assert any("finite-grid cell selection" in warning for warning in result["warnings"])


def test_sample_regions_validates_scale_projection_and_tile_scale(ee, local):
    with pytest.raises(UnsupportedEEError, match="projection requires"):
        compile_expression(encode(ee, sample(ee, projection=ee.Projection("EPSG:32610"), scale=None)),
                           local[0], local[1])
    with pytest.raises(UnsupportedEEError, match="tileScale=1"):
        compile_expression(encode(ee, sample(ee, tileScale=2)), local[0], local[1])


def test_sample_regions_missing_and_unknown_parameters_are_rejected(ee, local):
    expression = encode(ee, sample(ee))
    calls = [node for _, node in expression.get("scope", [])
             if isinstance(node, dict) and node.get("functionName") == "Image.sampleRegions"]
    assert calls

    missing = deepcopy(expression)
    target = next(node for _, node in missing["scope"]
                  if isinstance(node, dict) and node.get("functionName") == "Image.sampleRegions")
    target["arguments"].pop("collection")
    with pytest.raises(UnsupportedEEError, match="requires collection"):
        compile_expression(missing, local[0], local[1])

    unknown = deepcopy(expression)
    target = next(node for _, node in unknown["scope"]
                  if isinstance(node, dict) and node.get("functionName") == "Image.sampleRegions")
    target["arguments"]["unexpected"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(unknown, local[0], local[1])
