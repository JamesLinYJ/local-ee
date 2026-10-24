"""Zero-band descriptions never manufacture a raster or load discarded pixels."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image
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
        catalog, items, _ = synthetic_inputs()
        yield ee, [catalog], items
    assert guard.evidence()["attempt_count"] == 0


def compile_sdk(context, value, **options):
    ee, catalog, items = context
    return compile_expression(
        ee.serializer.encode(value, for_cloud_api=False), catalog, items, **options,
    )


def test_graph_rejects_empty_output_before_allocating_any_node():
    graph = Graph(Translator([], {}, {"scale": 30, "crs": "EPSG:32631"}))
    with pytest.raises(UnsupportedEEError, match="Zero-band Images contain no raster bands"):
        graph.image(Image([], {"owner": "left"}))
    assert graph.graph == {}
    assert graph.sources == {}


@pytest.mark.parametrize("source_backed", [False, True])
def test_metadata_describes_empty_schema_without_source_load(context, monkeypatch, source_backed):
    ee, _, _ = context
    source = ee.Image("scene-a") if source_backed else ee.Image()
    empty = source.select([]).set("details", {"values": [1, 2]})

    def forbidden_load(*_args, **_kwargs):
        raise AssertionError("metadata requested discarded raster pixels")

    monkeypatch.setattr(Graph, "source", forbidden_load)
    result = compile_sdk(context, empty, for_image_metadata=True)
    assert result["kind"] == "image"
    assert result["bands"] == []
    assert result["properties"]["details"] == {"values": [1, 2]}
    assert result["metadata_only"] is True
    assert "process_graph" not in result
    assert result["has_time_dimension"] is False
    assert result["source_item_ids"] == (["scene-a"] if source_backed else [])


def test_bandless_catalog_metadata_retains_real_ids_without_raster_nodes(context):
    ee, _, items = context
    empty = ee.ImageCollection("sentinel-2-l2a").select([])
    result = compile_sdk(context, empty, for_image_metadata=True)
    assert result["kind"] == "collection"
    assert result["bands"] == []
    assert result["has_time_dimension"] is True
    assert result["source_item_ids"] == [item["id"] for item in items["sentinel-2-l2a"]]
    assert "process_graph" not in result


def test_metadata_flag_does_not_change_nonempty_raster_graph(context):
    ee, _, _ = context
    value = ee.Image("scene-a").select("red").multiply(2)
    assert compile_sdk(context, value, for_image_metadata=True) == compile_sdk(context, value)


def test_metadata_return_is_detached_from_internal_image(monkeypatch):
    image = Image([], {"nested": {"values": [1]}})
    monkeypatch.setattr(Translator, "evaluate", lambda *_args: image)
    result = compile_expression(0, [], {}, for_image_metadata=True)
    result["properties"]["nested"]["values"].append(2)
    assert image.props == {"nested": {"values": [1]}}


def test_default_output_cannot_use_metadata_flag_implicitly(context):
    ee, _, _ = context
    with pytest.raises(UnsupportedEEError, match="Zero-band Images contain no raster bands"):
        compile_sdk(context, ee.Image().select([]))


def test_missing_source_and_unsupported_algorithm_still_fail_before_description(context):
    ee, _, _ = context
    with pytest.raises(UnsupportedEEError, match="not locally available"):
        compile_sdk(context, ee.Image("not-present").select([]), for_image_metadata=True)
    # Selecting no bands must not turn an unimplemented computation into a
    # successful description merely by erasing its output schema.
    with pytest.raises(UnsupportedEEError):
        compile_sdk(context, ee.Image("scene-a").resample("bicubic").select([]),
                    for_image_metadata=True)
