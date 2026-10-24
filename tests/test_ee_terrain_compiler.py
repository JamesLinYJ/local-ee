"""Pinned SDK serialization and bounded Earth Engine Terrain compiler checks."""
from copy import deepcopy
from pathlib import Path
import struct

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.terrain_spec import decode_terrain_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
EXPORT_REGION = {"type": "Polygon", "coordinates": [[
    [100.3, 30.3], [100.7, 30.3], [100.7, 30.7],
    [100.3, 30.3],
]]}


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


def compile_sdk(ee, value, *, items=None, options=None):
    metadata, default_items, _ = synthetic_inputs()
    return compile_expression(
        encode(ee, value), [metadata],
        default_items if items is None else items, options=options,
    )


def terrain_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_terrain"]


def terrain_specs(result):
    return [decode_terrain_spec(node["arguments"]["spec"])
            for node in terrain_nodes(result)]


def algorithm_calls(expression, name):
    return [node for _, node in expression.get("scope", [])
            if isinstance(node, dict) and node.get("functionName") == name]


def f64(value):
    return struct.pack(">d", value).hex()


def elevation_image(ee):
    return (ee.ImageCollection("sentinel-2-l2a").first()
            .select("nir").rename("elevation"))


def grid_items():
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    return metadata, items


def test_official_products_and_individual_sdk_calls_compile_with_named_outputs(ee):
    image = elevation_image(ee).set("local-tag", "terrain-retained")
    products = compile_sdk(ee, ee.Terrain.products(image))

    assert products["bands"] == ["elevation", "slope", "aspect", "hillshade"]
    assert products["properties"]["local-tag"] == "terrain-retained"
    assert [spec["operation"] for spec in terrain_specs(products)] == [
        "slope", "aspect", "hillshade",
    ]
    for name, method in (("slope", ee.Terrain.slope),
                         ("aspect", ee.Terrain.aspect),
                         ("hillshade", ee.Terrain.hillshade)):
        result = compile_sdk(ee, method(image))
        assert result["bands"] == [name]
        assert result["properties"]["local-tag"] == "terrain-retained"
        assert [spec["operation"] for spec in terrain_specs(result)] == [name]


def test_hillshade_defaults_nulls_and_periodic_angles_use_canonical_specs(ee):
    image = elevation_image(ee)
    omitted = encode(ee, ee.Terrain.hillshade(image))
    explicit_null = encode(ee, ee.Terrain.hillshade(
        image, azimuth=None, elevation=None,
    ))
    assert algorithm_calls(omitted, "Terrain.hillshade")
    assert algorithm_calls(explicit_null, "Terrain.hillshade")
    default_result = compile_sdk(ee, ee.Terrain.hillshade(image))
    null_result = compile_sdk(ee, ee.Terrain.hillshade(
        image, azimuth=None, elevation=None,
    ))
    assert terrain_specs(default_result) == terrain_specs(null_result) == [{
        "azimuth": f64(270.0), "elevation": f64(45.0),
        "operation": "hillshade", "v": 1,
    }]

    custom = compile_sdk(ee, ee.Terrain.hillshade(
        image, azimuth=630, elevation=-300,
    ))
    assert terrain_specs(custom) == [{
        "azimuth": f64(270.0), "elevation": f64(60.0),
        "operation": "hillshade", "v": 1,
    }]


def test_terrain_products_preserves_all_bands_and_rejects_output_collisions(ee):
    image = (ee.ImageCollection("sentinel-2-l2a").first()
             .select(["nir", "red"], ["elevation", "red"]))
    result = compile_sdk(ee, ee.Terrain.products(image))
    assert result["bands"] == ["elevation", "red", "slope", "aspect", "hillshade"]

    collision = image.addBands(
        srcImg=ee.Image.constant(1).rename("slope"),
    )
    with pytest.raises(UnsupportedEEError, match="collide with input bands"):
        compile_sdk(ee, ee.Terrain.products(collision))


def test_terrain_requires_one_band_or_named_elevation_and_scalar_source(ee):
    multiband = ee.ImageCollection("sentinel-2-l2a").first().select(["nir", "red"])
    with pytest.raises(UnsupportedEEError, match="band named 'elevation'"):
        compile_sdk(ee, ee.Terrain.products(multiband))
    with pytest.raises(UnsupportedEEError, match="scalar Image"):
        compile_sdk(ee, ee.Terrain.slope(elevation_image(ee).toArray()))
    with pytest.raises(UnsupportedEEError, match="finite bound raster source"):
        compile_sdk(ee, ee.Terrain.slope(ee.Image.constant(4).rename("elevation")))


def test_terrain_rejects_nonstatic_nonfinite_and_extra_sdk_arguments(ee):
    image = elevation_image(ee)
    with pytest.raises(UnsupportedEEError, match="finite static number"):
        compile_sdk(ee, ee.Terrain.hillshade(image, azimuth=ee.Image.constant(90)))
    with pytest.raises(UnsupportedEEError, match="finite static number"):
        compile_sdk(ee, ee.Terrain.hillshade(image, elevation=True))
    for angle in (float("nan"), float("inf")):
        with pytest.raises(UnsupportedEEError, match="finite static number"):
            compile_sdk(ee, ee.Terrain.hillshade(image, azimuth=angle))
    with pytest.raises(UnsupportedEEError, match="exact Float64 domain"):
        compile_sdk(ee, ee.Terrain.hillshade(image, azimuth=2**60))

    expression = deepcopy(encode(ee, ee.Terrain.products(image)))
    invocation = algorithm_calls(expression, "Terrain.products")[0]
    invocation["arguments"]["unexpected"] = 1
    metadata, items, _ = synthetic_inputs()
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, [metadata], items)


def test_deprecated_terrain_alias_maps_to_products(ee):
    result = compile_sdk(ee, ee.Algorithms.Terrain(elevation_image(ee)))
    assert result["bands"] == ["elevation", "slope", "aspect", "hillshade"]
    assert [spec["operation"] for spec in terrain_specs(result)] == [
        "slope", "aspect", "hillshade",
    ]
    assert any("deprecated alias" in warning for warning in result["warnings"])


def test_mapped_and_mosaicked_terrain_retain_ordered_source_identity(ee):
    collection = ee.ImageCollection("sentinel-2-l2a")
    metadata, items = grid_items()
    mapped = compile_expression(encode(ee, collection.map(
        lambda image: ee.Terrain.slope(image.select("nir").rename("elevation")),
    )), [metadata], items)
    assert mapped["kind"] == "collection"
    assert mapped["has_time_dimension"] is True
    assert mapped["bands"] == ["slope"]
    assert len(terrain_nodes(mapped)) == 1

    mosaic = collection.select(["nir"], ["elevation"]).mosaic()
    result = compile_expression(encode(ee, ee.Terrain.products(mosaic)), [metadata], items)
    assert result["source_item_ids"] == ["scene-a", "scene-b", "scene-c"]
    assert result["bands"] == ["elevation", "slope", "aspect", "hillshade"]
    ids = [node["process_id"] for node in result["process_graph"].values()]
    assert (ids.index("local_ee_to_double")
            < ids.index("local_ee_reduce_bands")
            < ids.index("local_ee_terrain"))


def test_multiscene_terrain_requires_proven_common_grid(ee):
    metadata, items = grid_items()
    image = (ee.ImageCollection("sentinel-2-l2a")
             .select(["nir"], ["elevation"]).mosaic())
    # Matching finite source transforms prove that the mosaicked elevation has
    # one local pixel grid; absent or conflicting metadata does not.
    compile_expression(encode(ee, ee.Terrain.slope(image)), [metadata], items)

    unproven_metadata, unproven_items, _ = synthetic_inputs()
    with pytest.raises(UnsupportedEEError, match="proj:transform evidence"):
        compile_expression(encode(ee, ee.Terrain.slope(image)),
                           [unproven_metadata], unproven_items)

    changed = deepcopy(items)
    changed["sentinel-2-l2a"][1]["properties"]["proj:transform"][2] += 5
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_expression(encode(ee, ee.Terrain.slope(image)), [metadata], changed)


def test_full_source_bounds_and_float64_conversion_precede_output_grid_changes(ee):
    image = elevation_image(ee).clip(
        ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9]),
    )
    with pytest.raises(UnsupportedEEError, match="Fractional image masks require a mask-aware consumer"):
        compile_sdk(ee, ee.Terrain.products(image),
                    options={"region": EXPORT_REGION, "scale": 40})
    image = elevation_image(ee).clip(
        ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9], geodesic=False),
    )
    result = compile_sdk(
        ee, ee.Terrain.products(image),
        options={"region": EXPORT_REGION, "scale": 40},
    )
    graph = result["process_graph"]
    nodes = list(graph.values())
    load = next(node for node in nodes if node["process_id"] == "load_collection")
    assert load["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }
    ids = [node["process_id"] for node in nodes]
    first_terrain = ids.index("local_ee_terrain")
    first_resample = ids.index("resample_spatial")
    assert ids.index("local_ee_to_double") < first_terrain < first_resample
    assert ids[-1] == "mask_polygon"


def test_terrain_work_budget_is_charged_before_output_construction():
    from gee.compat.earthengine.image_terrain import invoke_terrain
    from gee.compat.earthengine.ir import Image, Pixel

    class Translator:
        steps = 49_990

        @staticmethod
        def allowed(arguments, names):
            assert set(arguments) <= names

        def warn(self, _warning):
            pass

    translator = Translator()
    image = Image([("elevation", Pixel("constant", (1.0,)))], {})
    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        invoke_terrain(translator, "Terrain.slope", {"input": image})
