"""Official-client DEM graph parity and existing export/snapshot boundaries."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_dem_catalog_helpers import compiler_catalog, dem_item
from ee_random_split_parity import JAVASCRIPT
from gee.dem_contract import COLLECTION_ID
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression, UnsupportedEEError
from gee.graph import collection_loads, materialize, validate
from gee.services.ee_budget import pixel_budget
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
ROI = [100.2, 30.2, 100.201, 30.201]
NAMES = {"elevation", "slope", "aspect", "hillshade", "products", "clipped_products"}


def _example():
    spec = importlib.util.spec_from_file_location(
        "local_dem_example", ROOT / "examples/51_GEE_python_local_dem.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _python():
    metadata, items = compiler_catalog([dem_item()])
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        region = ee.Geometry.Rectangle(ROI, "EPSG:4326", False)
        outputs = _example().build_workflow(ee, region)
        compiled = {
            name: compile_expression(
                ee.serializer.encode(image, for_cloud_api=False), metadata, items,
            )
            for name, image in outputs.items()
        }
        task = _example().build_export_task(
            ee, outputs["clipped_products"], region,
            output_crs="EPSG:32647", output_scale=30,
        )
        config = task.config
    assert guard.evidence()["attempt_count"] == 0
    assert set(compiled) == NAMES
    return compiled, config, metadata, items


def _javascript():
    node = shutil.which("node") or str(
        ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    )
    if not Path(node).is_file():
        pytest.skip("Pinned JavaScript serialization requires Node")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const region=ee.Geometry.Rectangle([100.2,30.2,100.201,30.201],'EPSG:4326',false);
const collection=ee.ImageCollection('cop-dem-glo-30').filterBounds(region);
const elevation=collection.first().select('elevation');
const products=ee.Terrain.products(elevation);
const outputs={elevation,slope:ee.Terrain.slope(elevation),
 aspect:ee.Terrain.aspect(elevation),hillshade:ee.Terrain.hillshade(elevation),
 products,clipped_products:products.clip(region)};
console.log(JSON.stringify({attempts,outputs:Object.fromEntries(
 Object.entries(outputs).map(([key,value])=>[key,ee.Serializer.encode(value)]))}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    return decoded["outputs"]


def test_official_python_js_dem_example_graphs_match_without_network():
    python, _, metadata, items = _python()
    javascript = {
        name: compile_expression(value, metadata, items)
        for name, value in _javascript().items()
    }
    assert javascript == python
    for compiled in python.values():
        validate(compiled["process_graph"])
        loads = collection_loads(compiled["process_graph"])
        assert list(loads.values()) == [(COLLECTION_ID, ["dem-a"])]
    assert python["products"]["bands"] == ["elevation", "slope", "aspect", "hillshade"]


def test_dem_export_budget_uses_output_projection_and_preserves_source_grid(tmp_path):
    compiled, config, metadata, items = _python()
    assert config["crs"] == "EPSG:32647"
    assert config["scale"] == 30
    assert config["maxPixels"] == 1_000_000
    assert config["fileFormat"] == "GeoTIFF"
    result = compiled["clipped_products"]
    west, south, east, north = ROI
    options = {"crs": config["crs"], "scale": config["scale"], "region": {
        "type": "Polygon", "coordinates": [[[west, south], [east, south],
            [east, north], [west, north], [west, south]]],
    }}
    budget = pixel_budget(result, items, options, config["maxPixels"])
    assert 0 < budget["conservative_pixels_per_band"] < 1_000_000
    assert budget["resolution"] == [30, 30]
    # Export needs a projected CRS; degrees must never be treated as metres.
    with pytest.raises(UnsupportedEEError, match="projected CRS"):
        pixel_budget(result, items, {}, 1_000_000)
    with pytest.raises(ValueError, match="exceeds maxPixels"):
        pixel_budget(result, items, options, 1)

    original = deepcopy(result["process_graph"])
    frozen = {COLLECTION_ID: {"collection": metadata[0], "items": items[COLLECTION_ID]}}
    executable = materialize(original, frozen, tmp_path)
    assert original == result["process_graph"]
    stac_loads = [node["arguments"] for node in executable.values()
                  if node["process_id"] == "load_stac"]
    assert len(stac_loads) == 1
    assert Path(stac_loads[0]["url"]).parent == tmp_path
    assert stac_loads[0]["bands"] == ["elevation"]
    assert stac_loads[0]["spatial_extent"] == {
        "west": 100.0, "south": 30.0, "east": 101.0, "north": 31.0,
    }
    assert any(node["process_id"] == "local_ee_terrain" for node in executable.values())
    assert not list(tmp_path.iterdir())  # Materialization does not resolve or write files.
