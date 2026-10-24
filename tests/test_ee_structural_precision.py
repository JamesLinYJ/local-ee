"""Value-preserving Float64 casts across shared pixel structure."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
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


def compile_sdk(ee, value):
    metadata, items, _ = synthetic_inputs()
    return compile_expression(encode(ee, value), [metadata], items)


def source(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


def _has_double_ancestor(process_graph, node):
    """Inspect top-level process references, excluding embedded callbacks."""
    pending = []

    def refs(value):
        if isinstance(value, dict):
            if set(value) == {"from_node"}:
                pending.append(value["from_node"])
            else:
                for key, child in value.items():
                    if key == "process_graph":
                        continue
                    refs(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                refs(child)

    refs(node["arguments"])
    seen = set()
    while pending:
        reference = pending.pop()
        if reference in seen:
            continue
        seen.add(reference)
        parent = process_graph[reference]
        if parent["process_id"] == "local_ee_to_double":
            return True
        refs(parent["arguments"])
    return False


def _install_float32_callback(monkeypatch):
    """Model the pinned callback's implicit Float32 input conversion."""
    import test_ee_translate

    original = test_ee_translate.callback

    def narrow(value):
        if isinstance(value, np.ndarray) and np.issubdtype(value.dtype, np.floating):
            return value.astype(np.float32).astype(np.float64)
        if isinstance(value, dict):
            return {key: narrow(child) for key, child in value.items()}
        if isinstance(value, list):
            return [narrow(child) for child in value]
        if isinstance(value, tuple):
            return tuple(narrow(child) for child in value)
        return value

    def float32_callback(graph, parameters):
        return original(graph, narrow(parameters))

    monkeypatch.setattr(test_ee_translate, "callback", float32_callback)


def _evaluate_distance_input(result, arrays):
    from test_ee_translate import evaluate_graph

    return evaluate_graph(
        result, arrays, grid=np.array([[100.5, 30.5]]),
        process_handlers={
            "local_ee_distance": lambda arguments, values: values[
                arguments["data"]["from_node"]
            ],
        },
    )


def _first_clip_mask_distance(ee, *, planar=False):
    options = {"geodesic": False} if planar else {}
    return (source(ee).select("nir")
            .clip(ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9], **options))
            .updateMask(ee.Image.constant(1))
            .distance(kernel=ee.Kernel.euclidean(0)))


def test_first_clip_update_mask_distance_keeps_actual_subnormal(ee, monkeypatch):
    with pytest.raises(UnsupportedEEError, match="Image.clip spherical geometry edges"):
        compile_sdk(ee, _first_clip_mask_distance(ee))
    result = compile_sdk(ee, _first_clip_mask_distance(ee, planar=True))
    process_graph = result["process_graph"]
    nodes = list(process_graph.values())
    drop = next(node for node in nodes
                if node["process_id"] == "local_ee_drop_single_time")
    clip = next(node for node in nodes if node["process_id"] == "mask_polygon")
    mask = next(node for node in nodes if node["process_id"] == "mask")
    distance = next(node for node in nodes
                    if node["process_id"] == "local_ee_distance")
    assert _has_double_ancestor(process_graph, drop)
    assert _has_double_ancestor(process_graph, clip)
    assert _has_double_ancestor(process_graph, mask)
    assert _has_double_ancestor(process_graph, distance)

    tiny = np.nextafter(np.float64(0), np.float64(1))
    arrays = {
        scene: {"nir": np.array([tiny], dtype=np.float64)}
        for scene in ("scene-a", "scene-b", "scene-c")
    }
    _install_float32_callback(monkeypatch)
    data, names, timed = _evaluate_distance_input(result, arrays)
    assert names == ["nir"] and not timed
    assert np.float64(data.reshape(-1)[0]).hex() == tiny.hex()


def test_float32_callback_fixture_proves_pre_rewrite_subnormal_loss(
        ee, monkeypatch):
    from gee.compat.earthengine.pixel_graph import PixelCompiler

    with pytest.raises(UnsupportedEEError, match="Image.clip spherical geometry edges"):
        compile_sdk(ee, _first_clip_mask_distance(ee))
    fixed = compile_sdk(ee, _first_clip_mask_distance(ee, planar=True))
    with monkeypatch.context() as disabled:
        disabled.setattr(
            PixelCompiler, "_prepare_double_structural_rewrite",
            lambda self, pixel: None,
        )
        pre_rewrite = compile_sdk(ee, _first_clip_mask_distance(ee, planar=True))

    tiny = np.nextafter(np.float64(0), np.float64(1))
    arrays = {
        scene: {"nir": np.array([tiny], dtype=np.float64)}
        for scene in ("scene-a", "scene-b", "scene-c")
    }
    _install_float32_callback(monkeypatch)
    fixed_data, _, _ = _evaluate_distance_input(fixed, arrays)
    narrowed_data, _, _ = _evaluate_distance_input(pre_rewrite, arrays)
    assert np.float64(fixed_data.reshape(-1)[0]).hex() == tiny.hex()
    assert np.float64(narrowed_data.reshape(-1)[0]) == 0


def test_ordered_mosaic_casts_each_scene_before_float64_distance(ee, monkeypatch):
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    collection = ee.ImageCollection("sentinel-2-l2a").select("nir")
    image = collection.mosaic().toDouble().distance(
        kernel=ee.Kernel.euclidean(0),
    )
    result = compile_expression(encode(ee, image), [metadata], items)
    graph = result["process_graph"]
    reducers = [node for node in graph.values()
                if node["process_id"] == "local_ee_reduce_bands"]
    assert reducers
    assert all(_has_double_ancestor(graph, node) for node in reducers)

    tiny = np.nextafter(np.float64(0), np.float64(1))
    arrays = {
        "scene-a": {"nir": np.array([1.0], dtype=np.float64)},
        "scene-b": {"nir": np.array([np.nan], dtype=np.float64)},
        "scene-c": {"nir": np.array([tiny], dtype=np.float64)},
    }
    _install_float32_callback(monkeypatch)
    data, names, timed = _evaluate_distance_input(result, arrays)
    assert names == ["nir"] and not timed
    assert np.float64(data.reshape(-1)[0]).hex() == tiny.hex()


def test_double_cast_keeps_float32_arithmetic_and_mean_boundaries(ee):
    selected = source(ee).select("nir")
    explicit_float = selected.toFloat().add(1).toDouble()
    arithmetic = compile_sdk(
        ee, explicit_float.distance(kernel=ee.Kernel.euclidean(0)),
    )["process_graph"]
    ids = [node["process_id"] for node in arithmetic.values()]
    to_float = ids.index("local_ee_to_float")
    to_double = ids.index("local_ee_to_double")
    callbacks = [index for index, process_id in enumerate(ids)
                 if process_id == "reduce_dimension"]
    assert callbacks and to_float < callbacks[-1] < to_double

    mean = ee.ImageCollection("sentinel-2-l2a").select("nir").mean().toDouble()
    reduced = compile_sdk(ee, mean)["process_graph"]
    mean_reducer = next(
        node for node in reduced.values()
        if node["process_id"] == "reduce_dimension"
        and any(
            child.get("process_id") == "mean"
            for child in node["arguments"]["reducer"]["process_graph"].values()
        )
    )
    to_double_node = next(
        node for node in reduced.values()
        if node["process_id"] == "local_ee_to_double"
    )
    nodes = list(reduced.values())
    assert nodes.index(mean_reducer) < nodes.index(to_double_node)


def test_source_free_mask_value_uses_existing_callback_policy(ee):
    image = (ee.Image.constant(1)
             .updateMask(source(ee).select("nir").gt(0))
             .toDouble())
    result = compile_sdk(
        ee, image.distance(kernel=ee.Kernel.euclidean(0)),
    )
    graph = result["process_graph"]
    assert sum(node["process_id"] == "local_ee_distance"
               for node in graph.values()) == 1
    nodes = list(graph.values())
    conditional = next(
        node for node in nodes
        if node["process_id"] == "reduce_dimension"
        and any(
            child.get("process_id") == "if"
            for child in node["arguments"]["reducer"]["process_graph"].values()
        )
    )
    to_double = next(node for node in nodes
                     if node["process_id"] == "local_ee_to_double")
    distance = next(node for node in nodes
                    if node["process_id"] == "local_ee_distance")
    assert nodes.index(conditional) < nodes.index(to_double) < nodes.index(distance)


def test_double_cast_crosses_preserve_mask_without_crossing_value_callback(ee):
    image = (source(ee).select("nir")
             .where(ee.Image.constant(1), ee.Image.constant(2))
             .toDouble())
    result = compile_sdk(
        ee, image.distance(kernel=ee.Kernel.euclidean(0)),
    )
    graph = result["process_graph"]
    mask = next(node for node in graph.values()
                if node["process_id"] == "mask")
    to_double = next(node for node in graph.values()
                     if node["process_id"] == "local_ee_to_double")
    nodes = list(graph.values())
    callback = next(node for node in nodes
                    if node["process_id"] == "reduce_dimension"
                    and node["arguments"]["dimension"] == "bands")
    assert _has_double_ancestor(graph, mask)
    assert nodes.index(callback) < nodes.index(to_double) < nodes.index(mask)


def test_structural_cast_rewrite_keeps_graph_cycle_work_and_node_caps():
    item = {"id": "scene-a", "bbox": [0, 0, 1, 1],
            "geometry": EXPORT_REGION, "properties": {}}
    catalog = [{"id": "sentinel-2-l2a",
                "cube:dimensions": {"bands": {"values": ["nir"]}}}]
    source_ir = Source("sentinel-2-l2a", ("scene-a",), ("nir",))
    leaf = Pixel("band", (source_ir, "nir"))

    translator = Translator(catalog, {"sentinel-2-l2a": [item]}, None)
    compiler = Graph(translator)
    cyclic = Pixel("clip", (leaf, EXPORT_REGION))
    object.__setattr__(cyclic, "args", (cyclic, EXPORT_REGION))
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compiler.expression(Pixel("to_double", (cyclic,)))

    translator = Translator(catalog, {"sentinel-2-l2a": [item]}, None)
    translator.steps = 49_998
    compiler = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        compiler.expression(Pixel(
            "to_double", (Pixel("clip", (leaf, EXPORT_REGION)),),
        ))

    translator = Translator(catalog, {"sentinel-2-l2a": [item]}, None)
    compiler = Graph(translator)
    compiler.graph = {
        f"n{index}": {"process_id": "noop", "arguments": {}}
        for index in range(499)
    }
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compiler.expression(Pixel(
            "to_double", (Pixel("clip", (leaf, EXPORT_REGION)),),
        ))
