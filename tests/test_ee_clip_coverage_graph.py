"""Fresh source, grid, budget and Pixel-graph checks for clip weights."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from gee.clip_coverage_spec import prepare_clip_coverage_spec
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_clip import _scan_existing_clip_state
from gee.compat.earthengine.ir import (
    ClipFootprintIdentity, Image, Pixel, Source, UnsupportedEEError,
)
from gee.compat.earthengine.clip_coverage_graph import compile_clip_coverage_pixel
from scripts.ee_python_api.probe_cases import synthetic_inputs


def _catalog(*, misalign_second=False):
    metadata, default_items, _ = synthetic_inputs()
    items = deepcopy(default_items)
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32649"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3000000]
    if misalign_second:
        items["sentinel-2-l2a"][1]["properties"]["proj:transform"][2] += 5
    return [metadata], items


def _geometry():
    return {
        "type": "Polygon",
        "coordinates": [[
            [100.1, 30.1], [100.9, 30.1], [100.9, 30.9],
            [100.1, 30.9], [100.1, 30.1],
        ]],
    }


def _pixel(source):
    return Pixel("band", (source, "nir"))


def _compile(translator, raw, spec=None):
    graph = Graph(translator)
    value = Pixel("clip_coverage", (
        raw, spec or prepare_clip_coverage_spec(_geometry()),
    ))
    result, label, timed = graph.expression(value)
    return graph, result, label, timed


def test_coverage_compiler_emits_one_float64_independent_weight_on_the_actual_grid():
    catalog, items = _catalog()
    translator = Translator(catalog, items, None)
    raw = _pixel(Source("sentinel-2-l2a", ("scene-a",), ("nir",)))

    graph, result, label, timed = _compile(translator, raw)

    assert graph.graph[result["from_node"]]["process_id"] == "local_ee_clip_coverage"
    assert label == "v"
    assert timed is True
    coverage = graph.graph[result["from_node"]]
    assert coverage["arguments"]["spec"] == prepare_clip_coverage_spec(_geometry())
    source = coverage["arguments"]["data"]
    named_source = graph.graph[source["from_node"]]
    assert named_source["process_id"] == "rename_labels"
    selected_source = graph.graph[named_source["arguments"]["data"]["from_node"]]
    assert selected_source["process_id"] == "filter_bands"
    assert graph.graph[selected_source["arguments"]["data"]["from_node"]][
        "process_id"
    ] == "load_collection"
    assert graph.sources


def test_coverage_rejects_a_temporal_single_source_with_misaligned_actual_items():
    catalog, items = _catalog(misalign_second=True)
    translator = Translator(catalog, items, None)
    source = Source("sentinel-2-l2a", ("scene-a", "scene-b"), ("nir",))
    raw = Pixel("reduce_t", (_pixel(source), "mean"))
    value = Pixel("clip_coverage", (raw, prepare_clip_coverage_spec(_geometry())))

    with pytest.raises(UnsupportedEEError, match="proven common pixel grid"):
        compile_clip_coverage_pixel(Graph(translator), value)


def test_coverage_rejects_composition_and_unbound_constant_grids_before_native_lowering():
    catalog, items = _catalog()
    spec = prepare_clip_coverage_spec(_geometry())
    source = Source("sentinel-2-l2a", ("scene-a",), ("nir",))
    weighted = Pixel("with_mask", (_pixel(source), Pixel("mask_validity", (_pixel(source),))))
    for raw, message in (
        (weighted, "earlier clip or fractional masks"),
        (Pixel("constant", (1,)), "one actual source-backed science lineage"),
    ):
        with pytest.raises(UnsupportedEEError, match=message):
            compile_clip_coverage_pixel(Graph(Translator(catalog, items, None)),
                                        Pixel("clip_coverage", (raw, spec)))


@pytest.mark.parametrize("unary_count,should_pass", [(95, True), (96, False)])
def test_clip_preflight_enforces_exact_pixel_graph_depth_with_tuple_edges(
    unary_count, should_pass,
):
    class Ledger:
        steps = 0

    pixel = Pixel("leaf", ())
    for _ in range(unary_count):
        pixel = Pixel("absolute", (pixel,))
    image = Image([("nir", pixel)], {})

    if should_pass:
        _scan_existing_clip_state(Ledger(), image)
    else:
        with pytest.raises(UnsupportedEEError, match="depth96"):
            _scan_existing_clip_state(Ledger(), image)


def test_child_graph_source_and_spec_scans_debit_the_parent_work_ledger():
    catalog, items = _catalog()
    translator = Translator(catalog, items, None)
    graph = Graph(translator)
    raw = _pixel(Source("sentinel-2-l2a", ("scene-a",), ("nir",)))
    spec = prepare_clip_coverage_spec(_geometry())
    before = translator.steps

    compile_clip_coverage_pixel(graph, Pixel("clip_coverage", (raw, spec)))

    assert translator.steps > before
    assert graph.work_owner is translator
    assert translator._pixel_facts_cache is not None


def test_envelope_record_reservation_precedes_the_native_s2_bounds_call(monkeypatch):
    from gee.compat.earthengine import spherical_native
    from gee.compat.earthengine.geometry_bounds import _ENVELOPE_RECORD_WORK
    from gee.compat.earthengine.geometry_preflight import measure_geometry
    from gee.compat.earthengine.spherical_preflight import native_work
    from gee.compat.earthengine.image_clip import _clip_coverage_spec

    geometry = _geometry()
    cost = measure_geometry(geometry)
    model_work = cost.nodes + cost.positions
    bounds_work = (
        1 + cost.nodes + 4 * (cost.positions + cost.ring_closures)
        + native_work(geometry)
    )
    translator = Translator(*_catalog(), None)
    translator.steps = (
        50_000 - model_work - bounds_work - _ENVELOPE_RECORD_WORK + 1
    )
    calls = []

    def unexpected(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("S2 was called without a fully reserved envelope record")

    monkeypatch.setattr(spherical_native, "run", unexpected)
    with pytest.raises(UnsupportedEEError, match="S2 bounds and envelope validation"):
        _clip_coverage_spec(translator, geometry)
    assert calls == []


def test_immutable_clip_footprint_identity_survives_image_snapshots_and_copies():
    from gee.compat.earthengine.owned_metadata_values import owned_metadata_copy
    from gee.compat.earthengine.scalar_image_snapshot import (
        restore_scalar_image, snapshot_scalar_image,
    )

    spec = prepare_clip_coverage_spec(_geometry())
    identity = ClipFootprintIdentity(
        spec, hashlib.sha256(spec.encode("ascii")).digest(),
    )
    source = Source("sentinel-2-l2a", ("scene-a",), ("red", "green", "blue"))
    image = Image(
        [(name, _pixel(source)) for name in source.names], {}, source=source,
        clip_footprint=identity,
    )
    translator = Translator(*_catalog(), None)

    snapshot = snapshot_scalar_image(translator, image)
    restored = restore_scalar_image(translator, snapshot)
    copied = owned_metadata_copy(translator, image)

    assert restored.clip_footprint is identity
    assert copied.clip_footprint is identity
