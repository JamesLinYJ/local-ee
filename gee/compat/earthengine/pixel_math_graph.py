"""Lower fixed Image math IR to the native, bounded Float32 pixel SPI."""
from __future__ import annotations

import math
from dataclasses import dataclass

from gee.pixel_math_contract import (
    PIXEL_MATH_ARITIES,
    pixel_math_arity,
    validate_pixel_math_operation,
)

from .ir import Image, Pixel, Source, const, fail
from .pixel_facts_cache import translator_pixel_facts_cache


_FLOAT64_ERROR = (
    "Float64 pixel arithmetic is not supported by the pinned callback backend; "
    "apply toFloat() explicitly before Image pixel math"
)
_MAX_TRANSLATOR_WORK = 50_000


@dataclass(frozen=True)
class _PixelFacts:
    sources: tuple = ()
    has_multi_grid_constant: bool = False
    requires_per_item: bool = False


class _PixelFactsWalker:
    """Memoized bounded IR scan for source lineage and deferred math facts."""

    def __init__(self, translator):
        self.translator = translator
        self.work = 0
        self.memo = {}
        self.active = set()
        self.shareability = {}
        self.shared_cache = translator_pixel_facts_cache(translator)

    def charge(self, amount):
        self.work += amount
        steps = getattr(self.translator, "steps", None)
        if (amount < 0 or self.work > _MAX_TRANSLATOR_WORK
                or type(steps) is int and steps + amount > _MAX_TRANSLATOR_WORK):
            fail("Earth Engine graph exceeds compilation limits")
        if type(steps) is int:
            self.translator.steps = steps + amount

    @staticmethod
    def _merge_sources(children):
        merged = []
        known = set()
        for child in children:
            for source in child.sources:
                if source not in known:
                    known.add(source)
                    merged.append(source)
        return tuple(merged)

    def _mark_shareable(self, value, shareable):
        self.shareability[id(value)] = (value, shareable)

    def _is_shareable(self, value):
        if type(value) in (type(None), bool, int, float, str, bytes):
            return True
        entry = self.shareability.get(id(value))
        return entry is not None and entry[0] is value and entry[1]

    def _shared_facts(self, value):
        if self.shared_cache is None:
            return None
        # Reserve both lookup and local-memo work before LRU promotion. A hit
        # pays for both; a miss conservatively pays the same bounded amount.
        self.charge(2)
        facts = self.shared_cache.lookup(value)
        if facts is not None:
            self.memo[id(value)] = (value, facts)
        return facts

    def inspect(self, value):
        if isinstance(value, Source):
            key = id(value)
            cached = self.memo.get(key)
            if cached is not None and cached[0] is value:
                return cached[1]
            if type(value.cid) is not str or type(value.ids) is not tuple:
                fail("Image pixel math has an invalid source lineage")
            source_shareable = type(value) is Source
            if source_shareable:
                # Prove the IDs are immutable before either lookup or insert;
                # a malformed nested value must never reuse cached facts.
                self.charge(1 + len(value.ids))
                source_shareable = all(type(item_id) is str for item_id in value.ids)
            if source_shareable:
                shared = self._shared_facts(value)
                if shared is not None:
                    self._mark_shareable(value, True)
                    return shared
            self.charge(1 + len(value.cid) + len(value.ids))
            facts = _PixelFacts(sources=((value.cid, value.ids),))
            self._mark_shareable(value, source_shareable)
            if source_shareable and self.shared_cache is not None:
                self.shared_cache.store(value, facts, self.charge)
            self.memo[key] = (value, facts)
            return facts

        if not isinstance(value, (Pixel, tuple, list)):
            if type(value) not in (type(None), bool, int, float, str, bytes):
                self._mark_shareable(value, False)
            return _PixelFacts()

        key = id(value)
        if key in self.active:
            fail("Cyclic pixel expression is unsupported")
        cached = self.memo.get(key)
        if cached is not None and cached[0] is value:
            return cached[1]

        pixel_cache_candidate = (
            type(value) is Pixel
            and type(value.args) is tuple
            and type(value.op) is str
            and type(value.boolean) is bool
        )
        if pixel_cache_candidate or type(value) is tuple:
            shared = self._shared_facts(value)
            if shared is not None:
                self._mark_shareable(value, True)
                return shared
        self.active.add(key)

        if isinstance(value, Pixel):
            self.charge(1 + len(value.args))
            if value.op.startswith("math_") and value.op[5:] not in PIXEL_MATH_ARITIES:
                fail(f"Unsupported Image pixel math operation: {value.op[5:]}")
            children = [self.inspect(argument) for argument in value.args]
            # Source tuple comparisons/hashes can scan every ordered item ID.
            # Charge that work before merging the child lineages.
            self.charge(sum(
                1 + len(cid) + len(ids)
                for child in children for cid, ids in child.sources
            ))
            sources = self._merge_sources(children)
            multi_grid = any(child.has_multi_grid_constant for child in children)
            if value.op == "on_grid" and len(value.args) >= 3:
                grid_source = value.args[2]
                multi_grid = multi_grid or (
                    isinstance(grid_source, Source) and len(grid_source.ids) > 1
                )
            is_math = value.op.startswith("math_")
            deferred_input = is_math and any(
                not child.sources or child.has_multi_grid_constant
                for child in children
            )
            facts = _PixelFacts(
                sources,
                multi_grid,
                deferred_input or any(child.requires_per_item for child in children),
            )
            shareable = (
                type(value) is Pixel
                and type(value.args) is tuple
                and type(value.op) is str
                and type(value.boolean) is bool
            )
            if type(value) is Pixel and type(value.args) is tuple:
                # Children were already inspected above, so this bounded scan
                # proves deep immutability without a second graph traversal.
                self.charge(1 + len(value.args))
                shareable = shareable and all(
                    self._is_shareable(argument) for argument in value.args
                )
        else:
            self.charge(1 + len(value))
            children = [self.inspect(child) for child in value]
            self.charge(sum(
                1 + len(cid) + len(ids)
                for child in children for cid, ids in child.sources
            ))
            facts = _PixelFacts(
                self._merge_sources(children),
                any(child.has_multi_grid_constant for child in children),
                any(child.requires_per_item for child in children),
            )
            shareable = type(value) is tuple
            if shareable:
                self.charge(1 + len(value))
                shareable = all(self._is_shareable(child) for child in value)

        self.active.remove(key)
        self.memo[key] = (value, facts)
        self._mark_shareable(value, shareable)
        if (shareable and self.shared_cache is not None
                and (type(value) is Pixel or type(value) is tuple)):
            self.shared_cache.store(value, facts, self.charge)
        return facts


def requires_per_item_pixel_math(image, translator):
    """Whether a compact mapped image would bind math constants across items.

    Real-raster math remains compact. Deferred scalar math and math that already
    carries a multi-item on-grid constant require singleton frame evaluation.
    """
    if not isinstance(image, Image):
        return False
    walker = _PixelFactsWalker(translator)
    # A previous unrelated math expression can set the translator's hint.
    # Skip source-ID scans for an ordinary mapped image even in that case.
    if not contains_pixel_math(image.bands, charge=walker.charge):
        return False
    return walker.inspect(image.bands).requires_per_item


def is_pixel_math(pixel):
    return (
        isinstance(pixel, Pixel)
        and pixel.op.startswith("math_")
        and pixel.op[5:] in PIXEL_MATH_ARITIES
    )


def contains_pixel_math(value, seen=None, *, charge=None):
    """Find fixed math in a deferred scalar expression without revisiting DAGs."""
    seen = set() if seen is None else seen
    if isinstance(value, Pixel):
        key = id(value)
        if key in seen:
            return False
        seen.add(key)
        if charge is not None:
            charge(1 + len(value.args))
        if value.op.startswith("math_"):
            if value.op[5:] not in PIXEL_MATH_ARITIES:
                fail(f"Unsupported Image pixel math operation: {value.op[5:]}")
            return True
        return any(contains_pixel_math(argument, seen, charge=charge) for argument in value.args)
    if isinstance(value, (tuple, list)):
        if charge is not None:
            charge(1 + len(value))
        return any(contains_pixel_math(argument, seen, charge=charge) for argument in value)
    return False


def source_for_pixel(pixel, seen=None):
    """Return the first real source carried by a raster expression."""
    seen = set() if seen is None else seen
    if isinstance(pixel, Pixel):
        key = id(pixel)
        if key in seen:
            return None
        seen.add(key)
        if pixel.op == "band" and len(pixel.args) == 2:
            source = pixel.args[0]
            return source if isinstance(source, Source) else None
        if pixel.op == "on_grid" and len(pixel.args) >= 3:
            source = pixel.args[2]
            if isinstance(source, Source):
                return source
        for argument in pixel.args:
            source = source_for_pixel(argument, seen)
            if source is not None:
                return source
    elif isinstance(pixel, (tuple, list)):
        for argument in pixel:
            source = source_for_pixel(argument, seen)
            if source is not None:
                return source
    return None


def bind_deferred_pixel_math(pixel, template):
    """Bind a constant-only math subtree to a sibling's actual raster grid."""
    source = source_for_pixel(template)
    if source is None or not source.ids:
        fail("Image pixel math constants require a finite local raster grid")
    from .constant_bands import bind_pixel_math_constants

    return bind_pixel_math_constants(pixel, template, source)


def _validate_atan2_lineage(graph, pixel):
    walker = _PixelFactsWalker(getattr(graph, "t", None))
    left = walker.inspect(pixel.args[0]).sources
    right = walker.inspect(pixel.args[1]).sources
    if len(left) > 1 or len(right) > 1:
        fail("Image.atan2 operands with multiple local source lineages cannot be aligned safely")
    if left and right and left != right:
        fail("Image.atan2 operands must use the same ordered source collection and item IDs")


def _materialized_operand(graph, value, template, source, operation):
    if isinstance(value, Pixel) and contains_pixel_math(value):
        from .constant_bands import bind_pixel_math_constants

        value = bind_pixel_math_constants(value, template, source)
    elif isinstance(value, Pixel):
        if value.op == "constant" and len(value.args) == 1 and type(value.args[0]) is bool:
            value = const(int(value.args[0]))
        grid_constant = Pixel("on_grid", (value, template, source, None, False),
                              boolean=value.boolean)
        value = Pixel("to_float", (grid_constant,))
    else:
        if type(value) is bool:
            value = int(value)
        if (type(value) not in (int, float)
                or type(value) is int and abs(value) > 2**53
                or type(value) is float and (
                    not math.isfinite(value) or abs(value) > 2**53
                )):
            fail(f"Image.{operation} requires finite numeric raster operands")
        grid_constant = Pixel("on_grid", (const(value), template, source, None, False))
        value = Pixel("to_float", (grid_constant,))
    ref, label, timed = graph.expression(value)
    if label is None:
        fail(f"Image.{operation} constants require a finite local raster grid")
    return ref, timed


def _compile_pixel_math(graph, pixel, operation):
    expected = pixel_math_arity(operation)
    if len(pixel.args) != expected:
        fail(f"Image.{operation} has an invalid internal operand count")
    if graph.has_double_precision(pixel):
        fail(_FLOAT64_ERROR)
    if operation == "atan2":
        # Generic openEO merge_cubes resamples mismatched inputs. This SDK
        # operation has no projection-aware alignment policy, so only merge
        # branches with one identical ordered source lineage.
        _validate_atan2_lineage(graph, pixel)

    results = [graph.expression(argument) for argument in pixel.args]
    raster_positions = [index for index, result in enumerate(results)
                        if result[1] is not None]
    if not raster_positions:
        # Keep pure Image.constant math deferred. It must bind to an actual
        # collection/template grid; the API compiler has no global pixel grid.
        return pixel, None, True

    first = raster_positions[0]
    template = pixel.args[first]
    source = source_for_pixel(template)
    if source is None or not source.ids:
        fail(f"Image.{operation} requires a finite local raster grid")
    timed = results[first][2]

    operands = []
    for index, result in enumerate(results):
        ref, label, has_time = result
        if label is not None:
            if has_time != timed:
                fail("Combining temporal collections and spatial Images needs unsupported time broadcasting")
        else:
            ref, has_time = _materialized_operand(
                graph, ref, template, source, operation,
            )
            if has_time != timed:
                fail("Image pixel math operands need matching spatial/temporal dimensions")
        # The local SPI accepts actual Float32 bands. Default and scalar
        # literals are normalized here; has_double_precision above keeps an
        # explicit toDouble() request from being silently narrowed.
        ref = graph.node("local_ee_to_float", data=ref)
        operands.append(graph.rename_band(ref, "x" if index == 0 else "y"))

    data = operands[0]
    if expected == 2:
        data = graph.node("merge_cubes", cube1=operands[0], cube2=operands[1])
    result = graph.node("local_ee_pixel_math", data=data, operation=operation)
    return result, "v", timed


def compile_pixel_math(graph, pixel):
    """Compile the `math_<operation>` Pixel op with exact contract arity."""
    if not isinstance(pixel, Pixel) or not pixel.op.startswith("math_"):
        fail("Internal Image pixel math compiler received an invalid node")
    operation = validate_pixel_math_operation(pixel.op[5:])
    return _compile_pixel_math(graph, pixel, operation)
