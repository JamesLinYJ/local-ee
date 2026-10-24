"""Zero-band Image.addBands accumulator paths stay finite and bounded."""
from __future__ import annotations

import pytest
from shapely.geometry import shape

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


@pytest.fixture
def context():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        metadata, items, _ = synthetic_inputs()
        yield ee, [metadata], items
    assert guard.evidence()["attempt_count"] == 0


def _evaluate(context, value):
    ee, catalog, items = context
    wire = ee.serializer.encode(value, for_cloud_api=False)
    return Translator(catalog, items, {}).evaluate(wire), wire


def _pixel_sources(value):
    found = []

    def visit(pixel):
        if not isinstance(pixel, Pixel):
            return
        if pixel.op == "band":
            found.append(pixel.args[0])
        for child in pixel.args:
            if isinstance(child, Pixel):
                visit(child)
            elif isinstance(child, (tuple, list)):
                for nested in child:
                    visit(nested)

    for _, pixel in value.bands:
        visit(pixel)
    return found


def _pixel_nodes(value):
    found = []

    def visit(pixel):
        if not isinstance(pixel, Pixel):
            return
        found.append(pixel)
        for child in pixel.args:
            if isinstance(child, Pixel):
                visit(child)
            elif isinstance(child, (tuple, list)):
                for nested in child:
                    visit(nested)

    visit(value)
    return found


def _rectangle(west, south, east, north):
    return {
        "type": "Polygon", "geodesic": False,
        "coordinates": [[[west, south], [east, south], [east, north],
                         [west, north], [west, south]]],
    }


def _raster(ee, order="first"):
    collection = ee.ImageCollection("sentinel-2-l2a")
    if order == "last":
        collection = collection.sort("system:time_start", ascending=False)
    return ee.Image(collection.first())


def test_zero_band_destination_accepts_actual_raster_and_keeps_first_properties(context):
    ee, _, _ = context
    destination = ee.Image().select([]).set("owner", "destination")
    raster = _raster(ee)
    result, _ = _evaluate(context, destination.addBands(raster))
    assert [name for name, _ in result.bands] == ["blue", "green", "red", "nir", "SCL"]
    assert result.props == {"owner": "destination"}
    assert shape(result.footprint).equals(shape(_rectangle(100, 30, 101, 31)))
    assert result.source.ids == ("scene-a",)
    assert len(_pixel_sources(result)) == len(result.bands)
    assert all(source == result.source for source in _pixel_sources(result))


def test_zero_band_source_cannot_import_discarded_raster_pixels(context):
    ee, _, _ = context
    raster = _raster(ee)
    empty_from_other_scene = _raster(ee, "last").select([])
    result, _ = _evaluate(context, raster.addBands(empty_from_other_scene))
    assert [name for name, _ in result.bands] == ["blue", "green", "red", "nir", "SCL"]
    assert result.source.ids == ("scene-a",)
    assert all(source.ids == ("scene-a",) for source in _pixel_sources(result))


def test_empty_destination_preserves_its_explicit_first_footprint(context):
    ee, catalog, items = context
    region = _rectangle(99, 29, 102, 32)
    source_footprint = _rectangle(100, 30, 101, 31)
    destination = _raster(ee).clip(region).select([]).set("owner", "clipped-first")
    added = _raster(ee, "last").select("red").rename("from_second")
    result, wire = _evaluate(context, destination.addBands(added))

    assert result.props["owner"] == "clipped-first"
    assert shape(result.footprint).equals(shape(source_footprint))
    assert result.bands[0][0] == "from_second"
    clipped = result.bands[0][1]
    assert clipped.op == "clip" and shape(clipped.args[1]).equals(shape(source_footprint))
    sources = _pixel_sources(result)
    assert len(sources) == 1 and sources[0].ids == ("scene-c",)

    compiled = compile_expression(wire, catalog, items)
    assert compiled["source_item_ids"] == ["scene-c"]
    loads = [node for node in compiled["process_graph"].values()
             if node["process_id"] == "load_collection"]
    assert [node["arguments"]["_gee_item_ids"] for node in loads] == [["scene-c"]]
    assert any(node["process_id"] == "mask_polygon"
               and shape(node["arguments"]["mask"]).equals(shape(source_footprint))
               for node in compiled["process_graph"].values())


def test_source_free_clipped_empty_accumulator_keeps_explicit_footprint(context):
    ee, _, _ = context
    region = _rectangle(100.1, 30.1, 100.4, 30.4)
    destination = ee.Image().clip(region).select([])
    added = _raster(ee).select("nir")
    result, _ = _evaluate(context, destination.addBands(added))
    assert shape(result.footprint).equals(shape(region))
    assert result.source.ids == ("scene-a",)
    assert result.bands[0][1].op == "clip"
    assert shape(result.bands[0][1].args[1]).equals(shape(region))


def test_absolute_empty_destination_footprint_skips_catalog_source(context):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    absolute = _rectangle(102, 32, 103, 33)
    unavailable = Source("not-a-local-collection", ("missing",), ("red",))
    destination = Image(
        [], {}, unavailable, footprint=absolute, footprint_is_absolute=True,
    )
    donor_source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    donor = Image([("blue", Pixel("band", (donor_source, "blue")))], {}, donor_source)

    result = translator.invoke("Image.addBands", {
        "dstImg": destination, "srcImg": donor,
    })

    assert shape(result.footprint).equals(shape(absolute))
    assert result.bands[0][1].op == "clip"
    assert shape(result.bands[0][1].args[1]).equals(shape(absolute))


def test_empty_accumulator_iterate_builds_ordered_raster_bands(context):
    ee, catalog, items = context
    raster = _raster(ee)
    value = ee.List(["nir", "red"]).iterate(
        lambda name, accumulator: ee.Image(accumulator).addBands(raster.select(name)),
        ee.Image().select([]),
    )
    result, wire = _evaluate(context, value)
    assert [name for name, _ in result.bands] == ["nir", "red"]
    compiled = compile_expression(wire, catalog, items)
    assert compiled["bands"] == ["nir", "red"]
    assert compiled["source_item_ids"] == ["scene-a"]


def test_add_bands_zero_band_budget_is_precharged_before_mutation():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    destination = Image([], {"owner": "first"})
    source = Image([], {})
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        translator.invoke("Image.addBands", {"dstImg": destination, "srcImg": source})
    assert translator.steps == 50_000
    assert destination.bands == []
    assert destination.props == {"owner": "first"}


def test_add_bands_precharges_both_inputs_and_oversized_names():
    translator = Translator([], {}, {})
    source_lineage = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    destination = Image([], {})
    source = Image([("blue", Pixel("band", (source_lineage, "blue")))], {}, source_lineage)
    translator.steps = 49_997
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        translator.invoke("Image.addBands", {"dstImg": destination, "srcImg": source})
    assert translator.steps == 49_998
    assert destination.bands == []
    assert source.bands[0][0] == "blue"

    translator = Translator([], {}, {})
    long_source = Image(
        [("n" * 25_000, Pixel("band", (source_lineage, "blue")))], {}, source_lineage,
    )
    with pytest.raises(UnsupportedEEError, match="compilation work budget"):
        translator.invoke("Image.addBands", {
            "dstImg": Image([], {}), "srcImg": long_source,
        })
    assert translator.steps == 4
    assert len(long_source.bands[0][0]) == 25_000


def test_empty_merge_does_not_use_a_weight_only_raster_as_its_grid(context):
    ee, catalog, items = context
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    weighted = Image(
        [("weighted", Pixel("with_mask", (const(1), Pixel("band", (source, "blue")))))],
        {}, source,
    )
    translator = Translator(catalog, items, {})
    with pytest.raises(UnsupportedEEError, match="mask branch"):
        translator.invoke("Image.addBands", {
            "dstImg": Image([], {}), "srcImg": weighted,
        })


def test_empty_merge_science_scan_rejects_cycles_and_depth_97(context):
    ee, catalog, items = context
    translator = Translator(catalog, items, {})
    cyclic = Pixel("identity", ())
    object.__setattr__(cyclic, "args", (cyclic,))
    with pytest.raises(UnsupportedEEError, match="Cyclic constant mask expression"):
        translator.invoke("Image.addBands", {
            "dstImg": Image([], {}), "srcImg": Image([("cycle", cyclic)], {}),
        })

    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    deep = Pixel("band", (source, "blue"))
    for _ in range(96):
        deep = Pixel("identity", (deep,))
    with pytest.raises(UnsupportedEEError, match="depth 96"):
        translator.invoke("Image.addBands", {
            "dstImg": Image([], {}), "srcImg": Image([("deep", deep)], {}, source),
        })


def test_empty_merge_detaches_nested_properties_and_footprint(context):
    ee, catalog, items = context
    translator = Translator(catalog, items, {})
    source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    original_footprint = _rectangle(100.1, 30.1, 100.8, 30.8)
    original_properties = {"nested": {"tags": ["first"]}}
    destination = Image([], original_properties, footprint=original_footprint)
    raster = Image([("blue", Pixel("band", (source, "blue")))], {}, source)

    result = translator.invoke("Image.addBands", {
        "dstImg": destination, "srcImg": raster,
    })

    result.props["nested"]["tags"].append("result")
    result.footprint["coordinates"][0][0][0] = 99
    assert original_properties["nested"]["tags"] == ["first"]
    assert original_footprint["coordinates"][0][0][0] == 100.1
    clip_geometry = result.bands[0][1].args[1]
    assert clip_geometry is not result.footprint
    assert clip_geometry["coordinates"][0][0][0] == 100.1


def test_empty_noop_detaches_point_footprint_without_clipping(context):
    ee, catalog, items = context
    translator = Translator(catalog, items, {})
    original_footprint = {"type": "Point", "coordinates": [100.5, 30.5]}
    destination = Image([], {}, footprint=original_footprint)

    result = translator.invoke("Image.addBands", {
        "dstImg": destination, "srcImg": Image([], {}),
    })

    assert result.bands == []
    assert result.footprint is not original_footprint
    result.footprint["coordinates"][0] = 99
    assert original_footprint["coordinates"] == [100.5, 30.5]


def test_addbands_owns_tuple_coordinate_footprints_and_preserves_geometry_model():
    source = Source("metadata-source", ("scene-a",), ("red",))
    donor_source = Source("science-source", ("scene-b",), ("red",))
    coordinates = (((0, 0), (2, 0), (2, 2), (0, 2), (0, 0)),)
    footprint = GeometryValue(
        {"type": "Polygon", "coordinates": coordinates, "geodesic": False},
        {"geodesic": False, "evenOdd": True}, validated=True,
    )
    donor_band = Pixel("clip", (Pixel("band", (donor_source, "red")), footprint))
    destination = Image([("red", donor_band)], {}, source, footprint=footprint)
    translator = Translator([], {}, {})

    result = translator.invoke("Image.addBands", {
        "dstImg": destination, "srcImg": Image([("k", const(7))], {}),
    })

    assert isinstance(result.footprint, GeometryValue)
    assert result.footprint is not footprint
    assert result.footprint.geometry_metadata["geodesic"] is False
    assert result.footprint.geometry_metadata["evenOdd"] is True
    assert result.footprint.geometry_metadata["crs"] == "EPSG:4326"
    result.footprint["coordinates"][0][0][0] = 99
    assert footprint["coordinates"] == coordinates
    bound = dict(result.bands)["k"]
    assert bound.op == "on_grid"
    assert bound.args[1] is donor_band
    assert bound.args[2] == donor_source
    assert result.source == source


def test_spherical_sidecar_survives_select_and_empty_raster_merge_rejects_it(context):
    ee, catalog, items = context
    translator = Translator(catalog, items, {})
    metadata_source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    donor_source = Source("sentinel-2-l2a", ("scene-b",), ("red",))
    coordinates = (((100, 30), (101, 30), (101, 31), (100, 31), (100, 30)),)
    footprint = GeometryValue(
        {"type": "Polygon", "coordinates": coordinates},
        {"geodesic": True, "evenOdd": True}, validated=True,
    )
    destination = Image([], {}, metadata_source, footprint=footprint)
    selected = translator.select(destination, [])
    assert isinstance(selected.footprint, GeometryValue)
    assert selected.footprint.geometry_metadata["geodesic"] is True

    donor = Image([("red", Pixel("band", (donor_source, "red")))], {}, donor_source)
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        translator.invoke("Image.addBands", {"dstImg": selected, "srcImg": donor})


def test_raw_tuple_planar_footprint_survives_select_merge_geometry_and_constants(context):
    ee, catalog, items = context
    translator = Translator(catalog, items, {})
    metadata_source = Source("sentinel-2-l2a", ("scene-a",), ("blue",))
    science_source = Source("sentinel-2-l2a", ("scene-b",), ("red",))
    coordinates = (((100.1, 30.1), (100.8, 30.1), (100.8, 30.8),
                    (100.1, 30.8), (100.1, 30.1)),)
    raw_tuple_footprint = {"type": "Polygon", "coordinates": coordinates}
    empty = translator.select(Image(
        [], {"owner": "first"}, metadata_source, footprint=raw_tuple_footprint,
    ), [])
    assert isinstance(empty.footprint, GeometryValue)
    assert empty.footprint.geometry_metadata["geodesic"] is False

    donor = Image([("red", Pixel("band", (science_source, "red")))], {}, science_source)
    merged = translator.invoke("Image.addBands", {"dstImg": empty, "srcImg": donor})
    assert isinstance(merged.footprint, GeometryValue)
    assert merged.footprint.geometry_metadata["geodesic"] is False
    assert merged.props == {"owner": "first"}
    geometry = translator.footprint(merged)
    assert geometry["geodesic"] is False
    assert shape(geometry).equals(shape(raw_tuple_footprint))

    with_constant = translator.invoke("Image.addBands", {
        "dstImg": merged, "srcImg": Image([("k", const(7))], {}),
    })
    bound = dict(with_constant.bands)["k"]
    assert bound.op == "on_grid"
    assert bound.args[2] == science_source
    assert isinstance(bound.args[3], GeometryValue)
    assert bound.args[3].geometry_metadata["geodesic"] is False


def test_weighted_constant_uses_science_source_not_metadata_or_mask_source():
    metadata_source = Source("metadata-source", ("scene-a",), ("old",))
    science_source = Source("science-source", ("scene-b",), ("red",))
    mask_source = Source("mask-source", ("scene-c",), ("mask",))
    science = Pixel("band", (science_source, "red"))
    mask = Pixel("mask_validity", (Pixel("band", (mask_source, "mask")),))
    destination_band = Pixel("with_mask", (science, mask))
    destination = Image([("red", destination_band)], {}, metadata_source)
    weighted = Pixel("with_mask", (const(7), const(0.25)))
    translator = Translator([], {}, {})

    result = translator.invoke("Image.addBands", {
        "dstImg": destination, "srcImg": Image([("fractional", weighted)], {}),
    })

    bound = dict(result.bands)["fractional"]
    assert bound.op == "with_mask"
    grid_constants = [node for node in _pixel_nodes(bound) if node.op == "on_grid"]
    assert len(grid_constants) == 2
    assert all(node.args[1] is destination_band for node in grid_constants)
    assert all(node.args[2] == science_source for node in grid_constants)
    assert all(node.args[2] != mask_source for node in grid_constants)
    assert result.source == metadata_source


def test_source_backed_weighted_band_skips_binding_context_scan(monkeypatch):
    from gee.compat.earthengine.constant_bands import bind_source_bands
    from gee.compat.earthengine import image_binding_context

    metadata_source = Source("metadata-source", ("scene-a",), ("old",))
    science_source = Source("science-source", ("scene-b",), ("red",))
    mask_source = Source("mask-source", ("scene-c",), ("mask",))
    science = Pixel("band", (science_source, "red"))
    weight = Pixel("mask_validity", (Pixel("band", (mask_source, "mask")),))
    source_backed = Pixel("with_mask", (science, weight))
    destination = Image([
        ("red", Pixel("identity", (science,))),
    ], {}, metadata_source)

    def unexpected_context_scan(*_args):
        pytest.fail("source-backed science must not scan a binding-only grid context")

    monkeypatch.setattr(image_binding_context, "binding_context", unexpected_context_scan)
    bound = bind_source_bands(
        Image([("weighted", source_backed)], {}), destination, Translator([], {}, {}),
    )
    assert bound == [("weighted", source_backed)]
