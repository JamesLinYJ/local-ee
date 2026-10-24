"""Pinned Python SDK compilation and bounded graph checks for Image.unmix."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.image_unmix import invoke_image_unmix
from gee.compat.earthengine.ir import Image, Pixel, Source
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.spectral_unmix_spec import decode_spectral_unmix_spec, prepare_spectral_unmix_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
ENDMEMBERS = [[0.8, 0.2, 0.1], [0.1, 0.7, 0.3], [0.05, 0.15, 0.9]]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
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
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [3, 0], [3, 1], [0, 1], [0, 0]]],
    }
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["blue", "green", "red"]}},
    }]
    items = {"sentinel-2-l2a": [{
        "id": "scene-a", "bbox": [0, 0, 3, 1], "geometry": geometry,
        "properties": {"system:index": "scene-a", "system:time_start": 1_000},
    }]}
    return catalog, items


def compile_value(ee, value, local):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, *local)


def test_sdk_unmix_emits_one_native_producer_and_component_bands(ee, local):
    source = (ee.ImageCollection("sentinel-2-l2a").first()
              .select(["red", "blue", "green"]).set("marker", "preserved"))
    value = source.unmix(ENDMEMBERS, sumToOne=True, nonNegative=True)
    result = compile_value(ee, value, local)

    assert result["kind"] == "image"
    assert result["bands"] == ["unmix_0", "unmix_1", "unmix_2"]
    assert result["properties"]["marker"] == "preserved"
    assert result["source_item_ids"] == ["scene-a"]
    producers = [(key, node) for key, node in result["process_graph"].items()
                 if node["process_id"] == "local_ee_unmix"]
    assert len(producers) == 1
    producer_id, producer = producers[0]
    assert set(producer["arguments"]) == {"data", "spec"}
    spec = decode_spectral_unmix_spec(producer["arguments"]["spec"])
    assert spec["sumToOne"] is True and spec["nonNegative"] is True
    assert len(spec["endmembers"]) == 3
    assert [len(row) for row in spec["endmembers"]] == [3, 3, 3]
    assert any(node["process_id"] == "merge_cubes"
               and node["arguments"].get("cube1")
               and node["arguments"].get("cube2")
               for node in result["process_graph"].values())
    assert any(node["process_id"] == "filter_bands"
               and node["arguments"].get("data") == {"from_node": producer_id}
               for node in result["process_graph"].values())


@pytest.mark.parametrize("sum_to_one,non_negative", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_all_constraint_combinations_reach_the_v1_wire(ee, local, sum_to_one, non_negative):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green", "red"])
    value = image.unmix(ENDMEMBERS, sum_to_one, non_negative)
    result = compile_value(ee, value, local)
    wire = next(node["arguments"]["spec"] for node in result["process_graph"].values()
                if node["process_id"] == "local_ee_unmix")
    decoded = decode_spectral_unmix_spec(wire)
    assert decoded["sumToOne"] is sum_to_one
    assert decoded["nonNegative"] is non_negative


def test_omitted_constraint_flags_use_the_documented_false_defaults(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green", "red"])
    result = compile_value(ee, image.unmix(ENDMEMBERS), local)
    wire = next(node["arguments"]["spec"] for node in result["process_graph"].values()
                if node["process_id"] == "local_ee_unmix")
    decoded = decode_spectral_unmix_spec(wire)
    assert decoded["sumToOne"] is False
    assert decoded["nonNegative"] is False


@pytest.mark.parametrize("value,message", [
    (lambda ee: ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green"])
     .unmix([[1.0, 0.0, 0.0]]), "match the ordered input band count"),
    (lambda ee: ee.ImageCollection("sentinel-2-l2a").first()
     .unmix([[1.0, 0.0, 0.0], [1.0, 2.0]]), "rectangular matrix"),
    (lambda ee: ee.ImageCollection("sentinel-2-l2a").first()
     .unmix([[1.0, True, 0.0]]), "finite real numbers"),
    (lambda ee: ee.ImageCollection("sentinel-2-l2a").first()
     .unmix(ENDMEMBERS, sumToOne=1), "must be booleans"),
    (lambda ee: ee.Image.constant([1, 2, 3]).unmix(ENDMEMBERS), "cannot fold"),
])
def test_sdk_unmix_rejects_bad_arguments_and_source_free_fold(ee, local, value, message):
    with pytest.raises(UnsupportedEEError, match=message):
        compile_value(ee, value(ee), local)


def test_clipped_real_sdk_source_reaches_the_native_unmix_producer(ee, local):
    image = ee.ImageCollection("sentinel-2-l2a").first().select(["blue", "green", "red"])
    roi = ee.Geometry.Polygon(
        [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]],
        proj="EPSG:4326", geodesic=False,
    )
    result = compile_value(ee, image.clip(roi).unmix(ENDMEMBERS), local)

    assert result["bands"] == ["unmix_0", "unmix_1", "unmix_2"]
    assert any(node["process_id"] == "mask_polygon"
               for node in result["process_graph"].values())
    assert sum(node["process_id"] == "local_ee_unmix"
               for node in result["process_graph"].values()) == 1


def _direct_unmix_graph():
    item = {"id": "scene-a", "bbox": [0, 0, 3, 1]}
    translator = Translator([], {"spectral-scenes": [item]}, {})
    return Graph(translator)


def _direct_unmix_operand(geometry=None):
    source = Source("spectral-scenes", ("scene-a",), ("blue",))
    band = Pixel("band", (source, "blue"))
    if geometry is None:
        return band
    return Pixel("clip", (band, geometry))


@pytest.mark.parametrize("mutation", ["coordinates", "sidecar"])
def test_mutated_clip_geometry_is_rejected_between_component_compiles(mutation):
    graph = _direct_unmix_graph()
    geometry = GeometryValue({
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]],
    })
    operands = (_direct_unmix_operand(geometry),)
    spec = prepare_spectral_unmix_spec([[1.0], [2.0]])

    from gee.compat.earthengine.unmix_graph import compile_unmix_component

    compile_unmix_component(graph, Pixel("unmix_component", (operands, spec, 0)))
    if mutation == "coordinates":
        geometry["coordinates"][0][1][0] = 3
    else:
        geometry.geometry_metadata["evenOdd"] = True
    with pytest.raises(UnsupportedEEError, match="input changed between component"):
        compile_unmix_component(graph, Pixel("unmix_component", (operands, spec, 1)))


def test_distinct_specs_can_share_the_same_ordered_operand_tuple():
    graph = _direct_unmix_graph()
    operands = (_direct_unmix_operand(),)
    first = prepare_spectral_unmix_spec([[1.0]])
    second = prepare_spectral_unmix_spec([[2.0]])

    from gee.compat.earthengine.unmix_graph import compile_unmix_component

    compile_unmix_component(graph, Pixel("unmix_component", (operands, first, 0)))
    compile_unmix_component(graph, Pixel("unmix_component", (operands, second, 0)))
    assert sum(node["process_id"] == "local_ee_unmix"
               for node in graph.graph.values()) == 2


def test_internal_component_rejects_shape_spec_index_and_source_mismatches():
    source = Source("spectral-scenes", ("scene-a",), ("blue",))
    operand = Pixel("band", (source, "blue"))
    spec = prepare_spectral_unmix_spec([[1.0]])
    graph = Graph(Translator([], {}, {}))

    from gee.compat.earthengine.unmix_graph import compile_unmix_component

    with pytest.raises(UnsupportedEEError, match="invalid specification"):
        compile_unmix_component(graph, Pixel("unmix_component", ((operand,), "{}", 0)))
    with pytest.raises(UnsupportedEEError, match="outside the output shape"):
        compile_unmix_component(graph, Pixel("unmix_component", ((operand,), spec, 1)))
    with pytest.raises(UnsupportedEEError, match="ordered input bands"):
        compile_unmix_component(graph, Pixel("unmix_component", ((operand, operand), spec, 0)))


def test_unmix_precharges_work_before_building_output_pixels():
    source = Source("spectral-scenes", ("scene-a",), ("blue",))
    image = Image([("blue", Pixel("band", (source, "blue")))], {})
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_image_unmix(
            translator, "Image.unmix", {"image": image, "endmembers": [[1.0]]},
        )
    assert translator.steps == 49_999
