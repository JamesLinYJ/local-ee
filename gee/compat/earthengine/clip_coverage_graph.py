"""Compile geodesic Image.clip weights through the trusted native producer."""
from __future__ import annotations

from .ir import Image, Pixel, UnsupportedEEError, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_GRAPH_NODES = 500
_FORBIDDEN_INPUT_OPS = frozenset({"clip", "clip_coverage", "with_mask"})


class _OwnerWork:
    """Route child-graph scans and source facts into the parent request ledger."""
    def __init__(self, graph):
        self.items = graph.t.items
        self.owner = graph.work_owner

    @property
    def steps(self):
        return self.owner.steps

    @steps.setter
    def steps(self, value):
        self.owner.steps = value

    @property
    def _pixel_facts_cache(self):
        return getattr(self.owner, "_pixel_facts_cache", None)

    @_pixel_facts_cache.setter
    def _pixel_facts_cache(self, value):
        self.owner._pixel_facts_cache = value


def _charge(graph, work, label):
    owner = graph.work_owner
    steps = getattr(owner, "steps", None)
    if (type(steps) is not int or steps < 0 or work < 0
            or steps + work > MAX_TRANSLATOR_WORK):
        fail(f"{label} exceeds the 50000-step compilation work budget")
    owner.steps = steps + work


def _reject_preexisting_clip_state(graph, pixel):
    seen, active = {}, set()

    def visit(value, depth):
        if not isinstance(value, (Pixel, tuple, list)):
            return 0
        if depth > 96:
            fail("Internal Image.clip Pixel graph exceeds depth96")
        identity = id(value)
        if identity in active:
            fail("Internal Image.clip Pixel graph contains a cycle")
        height = seen.get(identity)
        if height is not None:
            _charge(graph, 1, "Image.clip native input revisit")
            if depth + height - 1 > 96:
                fail("Internal Image.clip Pixel graph exceeds depth96")
            return height
        if isinstance(value, Pixel):
            if type(value.op) is not str or type(value.args) is not tuple:
                fail("Internal Image.clip Pixel is malformed")
            _charge(graph, 1 + len(value.op) + len(value.args),
                    "Image.clip native input walk")
            if value.op in _FORBIDDEN_INPUT_OPS:
                fail("Image.clip coverage cannot compose with earlier clip or fractional masks")
            children = value.args
        else:
            _charge(graph, 1 + len(value), "Image.clip native input container scan")
            children = value
        active.add(identity)
        child_height = max(
            (visit(child, depth + 1) for child in children), default=0,
        )
        active.remove(identity)
        height = 1 + child_height
        if depth + height - 1 > 96:
            fail("Internal Image.clip Pixel graph exceeds depth96")
        seen[identity] = height
        return height

    visit(pixel, 1)


def compile_clip_coverage_pixel(graph, pixel):
    """Return Float64 cell weights on a real single-band input grid."""
    if (not isinstance(pixel, Pixel) or pixel.op != "clip_coverage"
            or type(pixel.args) is not tuple or len(pixel.args) != 2
            or not isinstance(pixel.args[0], Pixel) or type(pixel.args[1]) is not str):
        fail("Internal Image.clip coverage Pixel is malformed")
    raw, spec = pixel.args

    # The payload can own a much larger nested copy than a normal operator.
    # Pay its complete scan/parse allowance before JSON decoding.
    _charge(graph, 2 * len(spec) + 8,
            "Image.clip canonical specification validation")
    try:
        from ...clip_coverage_spec import decode_clip_coverage_spec

        decode_clip_coverage_spec(spec)
    except UnsupportedEEError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Image.clip canonical specification is invalid: {exc}")

    _reject_preexisting_clip_state(graph, raw)
    from .pixel_math_graph import _PixelFactsWalker

    facts = _PixelFactsWalker(_OwnerWork(graph)).inspect(raw)
    if len(facts.sources) != 1:
        fail("Image.clip coverage requires one actual source-backed science lineage")
    cid, ids = facts.sources[0]
    if type(cid) is not str or not cid or type(ids) is not tuple or not ids:
        fail("Image.clip coverage requires a finite actual raster source and grid")
    from .numeric_reducer_grid import require_common_grid

    require_common_grid(
        _OwnerWork(graph), (raw,), label="Image.clip coverage",
        check_single_item_assets=True,
    )

    from .sampled_training import image_node_estimate, image_work_estimate

    input_image = Image([("clip_input", raw)], {})
    try:
        # The estimate is bounded by the just-paid fresh IR walk. Its work is
        # charged to the owner even when this Graph is a sample child graph.
        work = image_work_estimate(input_image) + len(spec) + 6
        node_bound = image_node_estimate(input_image, graph.t.options) + 2
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail("Image.clip coverage exceeds the compilation work budget")
    _charge(graph, work, "Image.clip source and graph preflight")
    graph.reserve_nodes(node_bound, "Image.clip coverage")

    data, label, timed = graph.expression(raw)
    if label is None or data is None:
        fail("Image.clip coverage requires an actual raster band; constants need an actual grid")
    result = graph.node("local_ee_clip_coverage", data=data, spec=spec)
    return result, "v", bool(timed)


__all__ = ["compile_clip_coverage_pixel"]
