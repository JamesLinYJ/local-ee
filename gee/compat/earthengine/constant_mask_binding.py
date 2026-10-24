"""Bind direct source-free weighted constants to an existing science grid."""
from __future__ import annotations

from dataclasses import replace

from .ir import Image, Pixel, Source, fail


_MASK_FOLDS = {
    "mask_guard": "apply",
    "mask_validity": "validity",
    "mask_update": "update",
    "mask_apply": "apply",
    "mask_result_value": "result_value",
}
_CARRIERS = frozenset({"with_mask"})
_MAX_WORK = 50_000
_MAX_DEPTH = 96
_UNKNOWN = object()


def _carrier(pixel: Pixel):
    """Return the direct carrier and outer casts, if this is a bindable shape."""
    casts = []
    current = pixel
    seen = set()
    while isinstance(current, Pixel) and current.op in {"to_float", "to_double"}:
        if id(current) in seen or len(casts) >= _MAX_DEPTH:
            fail("Constant mask binding exceeds the depth 96 limit")
        seen.add(id(current))
        if type(current.args) is not tuple or len(current.args) != 1 or not isinstance(current.args[0], Pixel):
            fail("Malformed cast around a constant image mask")
        casts.append(current)
        current = current.args[0]
    if current.op not in _CARRIERS:
        return None
    if (type(current.args) is not tuple or len(current.args) != 2
            or any(not isinstance(value, Pixel) for value in current.args)):
        fail("Malformed independent image mask")
    return current, casts


def is_masked_constant_candidate(pixel: Pixel) -> bool:
    """Cheap shape check; full validation and accounting happen on bind."""
    return _carrier(pixel) is not None


def _charge_closure(translator, band_name: str, pixel: Pixel, destination: Image) -> None:
    """Precharge complete immutable closure work without using a graph ledger."""
    steps = getattr(translator, "steps", None)
    if type(steps) is not int or steps < 0 or steps > _MAX_WORK:
        fail("Constant mask binding requires the shared50000-step work budget")
    from .scalar_work_plan import plan_scalar_input_work

    if type(destination.bands) is not list:
        fail("Constant mask binding requires a finite destination band list")
    band_count = len(destination.bands)
    # Reserve destination-band enumeration before handing the existing list
    # to the planner. No expanded/copy list is constructed.
    if band_count > _MAX_WORK - steps:
        fail("Constant mask binding exceeds the shared50000-step compilation work budget")
    remaining = _MAX_WORK - steps - band_count
    # Plan the candidate and destination independently so the destination's
    # already-owned list is scanned in place. The full destination plan also
    # checks occurrence depth before destination_template's memoized lineage
    # scans run; no shared ledger entries or cache discounts are reused.
    source_plan = plan_scalar_input_work(
        Image([(band_name, pixel)], {}), None,
        max_inspection_work=remaining,
        max_cache_entries=0,
    )
    if not source_plan.safe:
        fail("Constant mask binding requires an immutable finite pixel expression")
    source_profile = source_plan.structural_work + source_plan.inspection_work
    destination_plan = plan_scalar_input_work(
        Image(destination.bands, {}), None,
        max_inspection_work=remaining - source_profile,
        max_cache_entries=0,
    )
    if not destination_plan.safe:
        fail("Constant mask binding requires an immutable finite destination grid")
    profile = (source_profile + destination_plan.structural_work
               + destination_plan.inspection_work + band_count)
    # One complete profile pays for the required graph scan. Three further
    # profiles cover scalar-fold validation, source/footprint checks and the
    # detached two-branch clone. There is no cross-call ledger credit.
    amount = 4 * profile + 16 + len(band_name)
    if steps + amount > _MAX_WORK:
        fail("Constant mask binding exceeds the shared50000-step compilation work budget")
    translator.steps = steps + amount


def _walk_pixels(value, depth=0, active=None, seen=None):
    if depth > _MAX_DEPTH:
        fail("Constant mask binding exceeds the depth 96 limit")
    active = set() if active is None else active
    seen = set() if seen is None else seen
    if isinstance(value, Pixel):
        key = id(value)
        if key in active:
            fail("Cyclic constant mask expression is unsupported")
        if key in seen:
            return
        seen.add(key)
        active.add(key)
        yield value
        for argument in value.args:
            yield from _walk_pixels(argument, depth + 1, active, seen)
        active.remove(key)
    elif isinstance(value, (tuple, list)):
        key = id(value)
        if key in active:
            fail("Cyclic constant mask expression is unsupported")
        if key in seen:
            return
        seen.add(key)
        active.add(key)
        for child in value:
            yield from _walk_pixels(child, depth + 1, active, seen)
        active.remove(key)


def _has_raster(pixel: Pixel, *, science_only=False) -> bool:
    """Find real band lineage, excluding a carrier's separate weight branch."""
    active = set()
    memo = {}

    def visit(value, depth):
        if depth > _MAX_DEPTH:
            fail("Constant mask binding exceeds the depth 96 limit")
        if not isinstance(value, Pixel):
            if isinstance(value, (tuple, list)):
                cached = memo.get(id(value))
                if cached is not None and cached[0] is value:
                    return cached[1]
                if id(value) in active:
                    fail("Cyclic constant mask expression is unsupported")
                active.add(id(value))
                result = any(visit(child, depth + 1) for child in value)
                active.remove(id(value))
                memo[id(value)] = (value, result)
                return result
            return False
        key = id(value)
        cached = memo.get(key)
        if cached is not None and cached[0] is value:
            return cached[1]
        if key in active:
            fail("Cyclic constant mask expression is unsupported")
        if value.op == "band":
            memo[key] = (value, True)
            return True
        active.add(key)
        try:
            if value.op == "with_mask":
                children = value.args[:1] if science_only else value.args
            elif science_only and value.op in {"mask_set_value", "mask_apply", "mask_result_value", "mask_guard"}:
                children = value.args[:1]
            else:
                children = value.args
            result = any(visit(child, depth + 1) for child in children)
            memo[key] = (value, result)
            return result
        finally:
            active.remove(key)

    return visit(pixel, 1)


def has_science_grid(pixel: Pixel) -> bool:
    """Whether a band carries an actual grid through its scientific value."""
    return _has_raster(pixel, science_only=True)


def _fold_closed_scalar(pixel: Pixel, memo=None, active=None, depth=0):
    """Validate source-free closed scalar mask projections using canonical folds."""
    if depth > _MAX_DEPTH:
        fail("Constant mask binding exceeds the depth 96 limit")
    memo = {} if memo is None else memo
    active = set() if active is None else active
    key = id(pixel)
    cached = memo.get(key)
    if cached is not None and cached[0] is pixel:
        return cached[1]
    if key in active:
        fail("Cyclic constant mask expression is unsupported")
    active.add(key)
    if pixel.op == "constant" and len(pixel.args) == 1:
        value = pixel.args[0]
        if value is None:
            result = None
        else:
            from .constant_bands import _evaluate

            result = _evaluate(pixel)
    elif pixel.op in _MASK_FOLDS:
        expected = 2 if pixel.op in {"mask_update", "mask_apply"} else 1
        if (type(pixel.args) is not tuple
                or len(pixel.args) != expected
                or any(not isinstance(child, Pixel) for child in pixel.args)):
            fail("Malformed constant mask projection")
        values = [_fold_closed_scalar(child, memo, active, depth + 1)
                  for child in pixel.args]
        if any(value is _UNKNOWN for value in values):
            result = _UNKNOWN
        else:
            from .mask_weights_graph import _fold

            result = _fold(_MASK_FOLDS[pixel.op], values + [1] if pixel.op == "mask_guard" else values)
    elif pixel.op == "mask_set_value":
        if (type(pixel.args) is not tuple or len(pixel.args) != 2
                or any(not isinstance(child, Pixel) for child in pixel.args)):
            fail("Malformed mask replacement science")
        values = [_fold_closed_scalar(child, memo, active, depth + 1)
                  for child in pixel.args]
        if any(value is _UNKNOWN for value in values):
            result = _UNKNOWN
        else:
            from .image_mask_setter import fold_set_value

            result = fold_set_value(*values)
    elif pixel.op == "if":
        if (type(pixel.args) is not tuple or len(pixel.args) != 3
                or any(not isinstance(child, Pixel) for child in pixel.args)):
            fail("Malformed closed scalar conditional")
        values = [_fold_closed_scalar(child, memo, active, depth + 1)
                  for child in pixel.args]
        if any(value is _UNKNOWN for value in values):
            result = _UNKNOWN
        else:
            condition = values[0]
            if condition is None:
                truth = False
            elif type(condition) in (bool, int, float):
                truth = bool(condition)
            else:
                result = _UNKNOWN
                truth = None
            if truth is not None:
                result = values[1] if truth else values[2]
    else:
        from .constant_bands import _BINARY, _CASTS, _UNARY, _evaluate

        allowed = set(_BINARY) | set(_UNARY) | set(_CASTS)
        if pixel.op not in allowed:
            result = _UNKNOWN
        elif (type(pixel.args) is not tuple
                or any(not isinstance(child, Pixel) for child in pixel.args)):
            result = _UNKNOWN
        else:
            values = [_fold_closed_scalar(child, memo, active, depth + 1)
                      for child in pixel.args]
            if any(value is _UNKNOWN for value in values):
                result = _UNKNOWN
            elif any(value is None for value in values):
                # Closed raster arithmetic propagates real NoData. Keep the
                # DAG intact; this fold only proves the setter's fill value.
                result = None
            else:
                folded = replace(pixel, args=tuple(Pixel("constant", (value,)) for value in values))
                result = _evaluate(folded)
    active.remove(key)
    memo[key] = (pixel, result)
    return result


def _on_grid(value: Pixel, template: Pixel, destination: Image) -> Pixel:
    return Pixel(
        "on_grid",
        (value, template, destination.source, destination.footprint,
         destination.footprint_is_absolute),
        value.boolean,
    )


def _bind_tree(pixel: Pixel, template: Pixel, destination: Image, memo, *, allow_nodata=False, depth=0):
    if depth > _MAX_DEPTH:
        fail("Constant mask binding exceeds the depth 96 limit")
    key = id(pixel)
    cached = memo.get(key)
    if cached is not None and cached[0] is pixel:
        return cached[1]
    if pixel.op == "clip":
        fail("Cannot bind a clipped constant band; its source footprint must be preserved")
    if pixel.op == "with_mask":
        fail("Nested fractional mask carriers require an explicitly audited consumer")
    if pixel.op == "constant":
        if type(pixel.args) is not tuple or len(pixel.args) != 1:
            fail("Malformed constant pixel in a masked band")
        value = pixel.args[0]
        if value is None:
            if not allow_nodata:
                fail("Cannot bind public Image.constant(None) as a raster band")
            # A missing scalar has no standalone grid. Preserve it as real
            # NoData through the canonical apply projection on the destination.
            zero = _on_grid(Pixel("constant", (0,)), template, destination)
            result = Pixel("mask_apply", (zero, zero))
        else:
            from .constant_bands import _literal

            _literal(value)
            result = _on_grid(pixel, template, destination)
        memo[key] = (pixel, result)
        return result
    if pixel.op in {"mask_guard", "mask_validity", "mask_update", "mask_apply", "mask_result_value", "mask_set_value"}:
        expected = 2 if pixel.op in {"mask_update", "mask_apply", "mask_set_value"} else 1
        if (type(pixel.args) is not tuple or len(pixel.args) != expected
                or any(not isinstance(child, Pixel) for child in pixel.args)):
            fail("Malformed constant mask projection")
        args = tuple(_bind_tree(child, template, destination, memo,
                                allow_nodata=True, depth=depth + 1)
                     for child in pixel.args)
        result = replace(pixel, args=args)
        memo[key] = (pixel, result)
        return result
    from .constant_bands import _BINARY, _CASTS, _UNARY

    if pixel.op not in set(_BINARY) | set(_UNARY) | set(_CASTS) | {"if"}:
        fail(f"Cannot bind masked constant expression with unsupported operation: {pixel.op}")
    if type(pixel.args) is not tuple:
        fail("Malformed masked constant expression")
    args = tuple(
        _bind_tree(child, template, destination, memo, allow_nodata=allow_nodata,
                   depth=depth + 1)
        if isinstance(child, Pixel) else child
        for child in pixel.args
    )
    result = replace(pixel, args=args)
    memo[key] = (pixel, result)
    return result


def bind_masked_pixel(
        pixel: Pixel, source: Image, destination: Image,
        translator, band_name: str) -> Pixel | None:
    """Bind only a direct source-free `with_mask` value/weight pair to a real grid.

    A source-backed raw science branch is already an actual raster and remains
    untouched. A raster found only in the independent weight branch cannot
    authorize materializing source-free science values.
    """
    shape = _carrier(pixel)
    if shape is None:
        return None
    carrier, outer_casts = shape
    from .constant_mask_lineage import scan_mask_lineage

    lineage = scan_mask_lineage(pixel, translator)
    raw, weight = carrier.args
    if lineage.science_raster:
        # Existing source-backed science already owns its grid. Do not run the
        # constant-only immutable planner over its clip geometry or rewrite it.
        return pixel
    if lineage.any_raster:
        fail("Masked sampling requires source-backed raw pixel values; source-free masked science cannot borrow a grid from its mask branch")

    _charge_closure(translator, band_name, pixel, destination)
    if source.footprint is not None or source.footprint_is_absolute:
        fail("Cannot bind a constant band with an explicit source footprint")
    if any(candidate.op == "clip" for candidate in _walk_pixels(pixel)):
        fail("Cannot bind a clipped constant band; its source footprint must be preserved")
    if (destination.source is None or not isinstance(destination.source, Source)
            or not destination.source.ids):
        fail("Masked constant bands require an actual science raster destination grid")

    # Locate the template only after the complete immutable input closure has
    # been precharged. A weight-only band cannot count as actual science grid.
    from .constant_bands import destination_template

    template = destination_template(destination, science_only=True)
    if template is None:
        fail("Masked constant bands require an actual science raster destination grid")

    # Fold source-free mask projections once for their canonical finite/range/
    # NoData checks. Keep the original Pixel DAG below so cast stages and the
    # nominal scientific dtype stay visible to the graph compiler.
    folded = tuple(_fold_closed_scalar(branch, memo={}) for branch in carrier.args)
    if any(value is _UNKNOWN for value in folded):
        fail("Masked constant binding accepts only closed scalar mask projections")
    from .mask_weights_graph import _fold

    # A direct scalar weight has no update/apply projection to trigger the
    # canonical finite [0,1] check, so validate it through the same update fold.
    _fold("update", (1.0, folded[1]))

    value = raw
    for cast in reversed(outer_casts):
        value = Pixel(cast.op, (value,), cast.boolean)
    # Keep the science and weight DAGs independently materialized even when
    # their source-free literal nodes happen to be shared in the input IR.
    bound_value = _bind_tree(value, template, destination, {})
    bound_weight = _bind_tree(weight, template, destination, {})
    return Pixel("with_mask", (bound_value, bound_weight), carrier.boolean)
