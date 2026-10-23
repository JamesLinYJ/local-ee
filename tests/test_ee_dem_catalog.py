"""Versioned local DEM admission and official Python SDK compilation."""
from copy import deepcopy
from pathlib import Path

import pytest

from ee_dem_catalog_helpers import (
    COLLECTION_ID,
    compiler_catalog,
    collection_metadata,
    dem_item,
)
from gee.dem_contract import (
    DEMContractError,
    MAX_RASTER_CELLS,
    validate_dem_collection,
    validate_dem_item,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def load(ee):
    return ee.ImageCollection(COLLECTION_ID)


def test_versioned_collection_contract_accepts_empty_and_unversioned_source_version():
    charges = []
    validate_dem_collection(collection_metadata(), [], charge=charges.append)
    item = dem_item()
    assert "gee:source_version" not in item["properties"]
    assert validate_dem_item(item, charge=charges.append) == item["id"]
    assert sum(charges) > 0


def test_empty_versioned_collection_is_admitted_until_first_needs_an_item(ee):
    with pytest.raises(UnsupportedEEError, match="Cannot take first image of an empty collection"):
        compile_expression(encode(ee, load(ee).first()),
                           [collection_metadata()], {COLLECTION_ID: []})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda metadata, items: metadata.pop("gee:dem_contract"), "must be a string"),
        (lambda metadata, items: metadata["gee:units"].update(elevation="ft"), "gee:units"),
        (lambda metadata, items: metadata["cube:dimensions"]["bands"].update(
            values=["elevation", "quality"]), "exactly"),
        (lambda metadata, items: items[0]["properties"].pop("gee:source_id"), "source_id"),
        (lambda metadata, items: items[0]["properties"].update(
            **{"gee:source_metadata_sha256": "A" * 64}), "lowercase SHA-256"),
        (lambda metadata, items: items[0]["properties"].update(
            **{"gee:vertical_datum": "EGM96"}), "vertical_datum"),
        (lambda metadata, items: items[0]["properties"]["gee:processing"]["elevation"].update(
            resampling="nearest"), "resampling must be none"),
        (lambda metadata, items: items[0]["properties"].update(
            datetime="2020-01-01T00:00:00"), "timezone-aware"),
        (lambda metadata, items: items[0]["bbox"].__setitem__(2, 102), "match its bbox"),
        (lambda metadata, items: items[0]["assets"]["elevation"].update(
            **{"proj:epsg": True}), "integer"),
        (lambda metadata, items: items[0]["assets"]["elevation"].update(
            **{"proj:shape": [MAX_RASTER_CELLS + 1, 1]}), "shape height"),
        (lambda metadata, items: items[0]["assets"]["elevation"].update(
            **{"proj:transform": [0.01, 1, 100, 0, -0.01, 31]}), "north-up"),
        (lambda metadata, items: items[0]["assets"].update(
            preview={"href": "file:///tmp/preview.tif"}), "too many fields"),
    ],
)
def test_dem_contract_rejects_malformed_or_ambiguous_metadata(mutate, message):
    metadata = collection_metadata()
    items = [dem_item()]
    mutate(metadata, items)
    with pytest.raises(DEMContractError, match=message):
        validate_dem_collection(metadata, items, charge=lambda count: None)


def test_dem_contract_rejects_duplicate_and_unsafe_item_ids():
    first = dem_item("same-id")
    duplicate = dem_item("same-id")
    with pytest.raises(DEMContractError, match="Duplicate DEM item id"):
        validate_dem_collection(collection_metadata(), [first, duplicate], charge=lambda n: None)

    unsafe = dem_item("../outside")
    with pytest.raises(DEMContractError, match="safe local path component"):
        validate_dem_item(unsafe, charge=lambda n: None)
    too_long = dem_item("x" * 251)
    with pytest.raises(DEMContractError, match="exceeds the metadata string limit"):
        validate_dem_item(too_long, charge=lambda n: None)


def test_legacy_unmarked_dem_fails_with_actionable_resync_guidance(ee):
    metadata = collection_metadata()
    metadata.pop("gee:dem_contract")
    with pytest.raises(UnsupportedEEError, match="resync/re-ingest.*cop-dem-glo-30/v1"):
        compile_expression(encode(ee, load(ee)), [metadata], {COLLECTION_ID: []})


@pytest.mark.parametrize("collection_id", ["COPERNICUS/DEM/GLO30", "uploaded-dem"])
def test_no_google_alias_or_arbitrary_uploaded_collection_is_admitted(ee, collection_id):
    metadata = [{"id": collection_id, "cube:dimensions": {
        "bands": {"values": ["elevation"]}}}]
    item = dem_item("other")
    item["collection"] = collection_id
    with pytest.raises(UnsupportedEEError, match="not locally ingested|not passed Earth Engine"):
        compile_expression(encode(ee, ee.ImageCollection(collection_id)), metadata,
                           {collection_id: [item]})


def test_official_python_sdk_compiles_dem_time_band_source_and_mask_semantics(ee):
    items = [
        dem_item("dem-before", "2020-01-01T23:59:59Z"),
        dem_item("dem-selected", "2020-01-02T00:00:00+00:00"),
        dem_item("dem-after", "2020-01-03T00:00:00Z"),
    ]
    catalog, item_map = compiler_catalog(items)
    selected = load(ee).filterDate(
        "2020-01-02T00:00:00Z", "2020-01-03T00:00:00Z"
    ).first().select(["elevation"])
    masked = selected.updateMask(selected.gt(0))
    result = compile_expression(encode(ee, masked), catalog, item_map)

    validate(result["process_graph"])
    assert result["kind"] == "image"
    assert result["bands"] == ["elevation"]
    assert result["source_item_ids"] == ["dem-selected"]
    loads = [node["arguments"] for node in result["process_graph"].values()
             if node["process_id"] == "load_collection"]
    assert len(loads) == 1
    assert loads[0]["id"] == COLLECTION_ID
    assert loads[0]["_gee_item_ids"] == ["dem-selected"]
    assert loads[0]["bands"] == ["elevation"]
    callbacks = [node["arguments"]["reducer"]["process_graph"]
                 for node in result["process_graph"].values()
                 if node["process_id"] == "reduce_dimension"
                 and "reducer" in node["arguments"]
                 and "process_graph" in node["arguments"]["reducer"]]
    callback_nodes = [node for callback in callbacks for node in callback.values()]
    assert any(node["process_id"] == "gt" for node in callback_nodes)
    assert any(node["process_id"] == "if"
               and node["arguments"].get("reject") is None
               for node in callback_nodes)


def test_dem_image_time_and_index_metadata_are_numeric_consistent_and_copyable(ee):
    from datetime import datetime

    selected_item = dem_item("dem-selected", "2020-01-02T00:00:00+00:00")
    selected_item["properties"]["system:time_start"] = 1_577_923_200_000.0
    catalog, item_map = compiler_catalog([selected_item])
    original_item_map = deepcopy(item_map)
    first_image = load(ee).first()
    direct_image = ee.Image("dem-selected")

    def value(expression):
        result = compile_expression(encode(ee, expression), catalog, item_map)
        assert result["kind"] == "value"
        return result["value"]

    # Match the live catalog service's datetime -> millisecond enrichment.
    expected_millis = datetime.fromisoformat(
        selected_item["properties"]["datetime"].replace("Z", "+00:00")
    ).timestamp() * 1000
    assert value(first_image.get("system:time_start")) == expected_millis
    assert value(first_image.date().millis()) == expected_millis
    assert value(first_image.get("system:index")) == "source-dem-selected"
    assert value(direct_image.get("system:time_start")) == expected_millis
    assert value(direct_image.date().millis()) == expected_millis
    assert value(direct_image.get("system:index")) == "source-dem-selected"

    copied = ee.Image.constant(0).copyProperties(
        first_image, ["system:time_start", "system:index"]
    )
    assert value(copied.get("system:time_start")) == expected_millis
    assert value(copied.get("system:index")) == "source-dem-selected"

    overridden = first_image.set("system:time_start", 42)
    assert value(overridden.get("system:time_start")) == 42
    assert item_map == original_item_map


def test_dem_catalog_rejects_preexisting_time_or_index_that_disagrees_with_source(ee):
    for property_name, property_value in (
        ("system:time_start", 1),
        ("system:index", "different-source"),
    ):
        item = dem_item("dem-bad-origin")
        item["properties"][property_name] = property_value
        catalog, item_map = compiler_catalog([item])
        with pytest.raises(UnsupportedEEError, match="does not match|must match"):
            compile_expression(
                encode(ee, ee.Image("dem-bad-origin")), catalog, item_map
            )


def test_dem_enrichment_precedes_inherited_and_copied_property_filtering():
    from dataclasses import replace
    from gee.compat.earthengine.decoder import Translator

    item = dem_item("dem-copy", "2020-01-02T00:00:00Z")
    catalog, item_map = compiler_catalog([item])
    translator = Translator(catalog, item_map, None)
    collection = translator.load(COLLECTION_ID)
    selected = replace(collection, image=replace(
        collection.image, inherit_props=False, copied_props=("system:time_start",)
    ))
    props = translator.properties(selected, "dem-copy")
    assert props == {"system:time_start": 1_577_923_200_000.0}


def test_dem_metadata_scans_use_the_shared_compiler_work_budget(ee):
    items = []
    for index in range(120):
        item = dem_item(f"dem-{index:03d}")
        items.append(item)
    catalog, item_map = compiler_catalog(items)
    with pytest.raises(UnsupportedEEError, match="shared 50000-step compilation work budget"):
        compile_expression(encode(ee, load(ee)), catalog, item_map)


def test_dem_graph_keeps_the_existing_500_node_limit(ee):
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.graph import Graph

    catalog, item_map = compiler_catalog([dem_item()])
    translator = Translator(catalog, item_map, None)
    source = translator.load(COLLECTION_ID).source
    graph = Graph(translator)
    graph.source(source)
    while len(graph.graph) < 500:
        graph.node("add", x=len(graph.graph), y=1)
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        graph.node("add", x=500, y=1)


def test_sentinel_two_collection_path_does_not_require_dem_contract(ee):
    metadata = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": ["nir"]}}}]
    item = {
        "id": "s2-a",
        "bbox": [100, 30, 101, 31],
        "geometry": dem_item()["geometry"],
        "properties": {"system:time_start": 0, "system:index": "s2-a"},
    }
    result = compile_expression(
        encode(ee, ee.ImageCollection("sentinel-2-l2a").first()),
        metadata, {"sentinel-2-l2a": [item]},
    )
    assert result["kind"] == "image"
    assert result["bands"] == ["nir"]


def test_normalized_128_point_scene_has_bounded_precharged_work():
    item = dem_item()
    west, south, east, north = item["bbox"]
    corners = [(west, south), (east, south), (east, north), (west, north)]
    points = []
    edge_steps = [32, 32, 32, 32]
    for (start, end), steps in zip(
        zip(corners, corners[1:] + corners[:1]), edge_steps
    ):
        for step in range(steps):
            fraction = step / steps
            points.append([
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            ])
    points.append(points[0])
    assert len(points) == 129  # 128 densified perimeter points plus ring closure.
    item["geometry"]["coordinates"] = [points]
    work = 0

    def charge(count):
        nonlocal work
        work += count

    validate_dem_item(item, charge=charge)
    assert work == 1488  # Including bounds for the 128-point ring and metadata keys.


def test_empty_and_multiring_geometries_are_not_silently_admitted():
    item = deepcopy(dem_item())
    item["geometry"]["coordinates"].append(item["geometry"]["coordinates"][0])
    with pytest.raises(DEMContractError, match="exactly one exterior ring"):
        validate_dem_item(item, charge=lambda count: None)
