"""Compile shared pixel IR into bounded native cube and callback processes."""
import math

from gee.float64_values_contract import FLOAT64_ARITIES
from gee.integer_values_contract import BOOLEAN_OPERATIONS

from .ir import Pixel, UnsupportedEEError, fail
from .static_values import scalar_power
from .temporal_graph import reduce_time


class PixelCompiler:
    def scalar_args(self, op, x, y=None):
        if op in {"min2", "max2"}: return ("min" if op == "min2" else "max"), {"data": [x, y], "ignore_nodata": False}
        if op == "power": return op, {"base": x, "p": y}
        if op == "mod": return op, {"x": x, "y": y}
        if op == "exp": return op, {"p": x}
        if op in {"log", "log10"}: return "log", {"x": x, "base": math.e if op == "log" else 10}
        if op == "if": fail("Internal conditional argument mismatch")
        return op, {"x": x, **({"y": y} if y is not None else {})}

    def expression(self, p):
        # Pixel expressions form a DAG. Quality selection and other conditionals
        # share subexpressions; revisiting the tree can otherwise take exponential
        # time even though node deduplication keeps the final graph small. Retain
        # the object alongside its identity so ephemeral IR objects cannot reuse
        # an ID and receive a different expression's cached result.
        key = id(p)
        if key not in self.expressions:
            self.expressions[key] = (p, self._expression(p))
        return self.expressions[key][1]

    def has_double_precision(self, p):
        # Pinned upstream pixel callbacks convert their input to Float32. Until
        # typed callbacks are implemented, reject these combinations rather
        # than silently narrowing an explicitly requested Float64 raster.
        key = id(p)
        if key not in self.double_precision:
            if p.op == "integer_values": result = not p.boolean
            elif p.op == "where": result = any(self.has_double_precision(value) for value in p.args[1:])
            elif p.boolean and p.op in BOOLEAN_OPERATIONS: result = False
            elif p.op in {"classify", "trained_classify", "smile_rf_classify", "fast_distance"}: result = False
            elif p.op in {"to_double", "unmask", "unmask_constant", "on_grid", "remap", "focal", "convolve", "neighborhood", "terrain", "distance"}: result = True
            elif p.op in {"to_float", "is_nodata"}: result = False
            else:
                operands = p.args[0] if p.op == "reduce_bands" else p.args[:1] if p.op in {"clip", "preserve_mask"} else p.args
                result = any(self.has_double_precision(x) for x in operands if isinstance(x, Pixel))
            self.double_precision[key] = (p, result)
        return self.double_precision[key][1]

    def _prepare_double_structural_rewrite(self, pixel):
        """Reserve work, then build one value-preserving cast rewrite."""
        if not isinstance(pixel, Pixel):
            return None
        cache = getattr(self, "_double_structural_cache", None)
        if cache is None:
            cache = self._double_structural_cache = {}
        key = id(pixel)
        cached = cache.get(key)
        if cached is not None and cached[0] is pixel:
            return cached[1]

        if pixel.op == "where" and not self.has_double_precision(pixel):
            # A cast after Float32 where must stay after its value callback,
            # while the existing structural mask rewrite still preserves it.
            steps = getattr(self.t, "steps", None)
            if type(steps) is not int or steps < 0 or steps + 20 > 50_000:
                fail("Earth Engine graph exceeds compilation limits")
            self.t.steps += 20
            from .pixel_selection_graph import where_float32

            rewrite = self._prepare_double_structural_rewrite(where_float32(*pixel.args))
            cache[key] = (pixel, rewrite)
            return rewrite

        kind = None
        if pixel.op == "clip" and len(pixel.args) == 2:
            kind = "clip"
        elif pixel.op == "preserve_mask" and len(pixel.args) == 2:
            kind = "preserve_mask"
        elif (pixel.op == "if" and len(pixel.args) == 3
                and isinstance(pixel.args[2], Pixel)
                and pixel.args[2].op == "constant"
                and pixel.args[2].args == (None,)):
            kind = "if"
        elif (pixel.op == "reduce_t" and len(pixel.args) >= 2
                and type(pixel.args[1]) is str
                and pixel.args[1] in {"first", "last"}):
            kind = "reduce_t"
        elif (pixel.op == "reduce_bands" and len(pixel.args) >= 2
                and type(pixel.args[1]) is str
                and pixel.args[1] in {"first", "last"}
                and isinstance(pixel.args[0], (tuple, list))
                and pixel.args[0]):
            kind = "reduce_bands"
        if kind is None:
            return None

        depth = getattr(self, "_double_structural_depth", 0)
        if depth >= 96:
            fail("Earth Engine graph exceeds compilation limits")
        work = 1 + len(pixel.args)
        if kind == "reduce_bands":
            # Reserve before scanning or allocating the rewritten input tuple.
            work += len(pixel.args[0])
        steps = getattr(self.t, "steps", None)
        if (type(steps) is not int or steps < 0 or steps + work > 50_000):
            fail("Earth Engine graph exceeds compilation limits")
        self.t.steps = steps + work

        if kind == "if":
            # Source-free accept values are outside the typed raster rewrite.
            # Keep their existing callback policy for scalar/grid binding.
            from .pixel_math_graph import _PixelFactsWalker

            if not _PixelFactsWalker(self.t).inspect(pixel.args[1]).sources:
                cache[key] = (pixel, None)
                return None
        if kind == "reduce_bands":
            # The typed band reducer needs a raster for every input. Mixed
            # source-free scalars keep the existing callback policy, which
            # owns their scalar/grid binding and precision behavior.
            if not all(isinstance(value, Pixel) for value in pixel.args[0]):
                cache[key] = (pixel, None)
                return None
            from .pixel_math_graph import _PixelFactsWalker

            facts = _PixelFactsWalker(self.t)
            if not all(facts.inspect(value).sources for value in pixel.args[0]):
                cache[key] = (pixel, None)
                return None

        rewrite = self._double_structural_rewrite(pixel, kind)
        cache[key] = (pixel, rewrite)
        return rewrite

    @staticmethod
    def _double_structural_rewrite(pixel, kind):
        """Move a Double cast through one value-preserving Pixel operation."""
        def cast(value):
            # Explicit toFloat and numeric operations are not structural, so
            # this wrapper stays outside them and preserves their precision.
            return Pixel("to_double", (value,))

        if kind == "clip":
            return Pixel("clip", (cast(pixel.args[0]), pixel.args[1]), pixel.boolean)
        if kind == "preserve_mask":
            return Pixel(
                "preserve_mask", (cast(pixel.args[0]), pixel.args[1]), pixel.boolean,
            )
        if kind == "if":
            return Pixel(
                "if", (pixel.args[0], cast(pixel.args[1]), pixel.args[2]),
                pixel.boolean,
            )
        if kind == "reduce_t":
            # Preserve optional order metadata such as mosaic's
            # collection_order marker while casting only selected values.
            return Pixel(
                "reduce_t", (cast(pixel.args[0]), *pixel.args[1:]), pixel.boolean,
            )
        if kind == "reduce_bands":
            return Pixel(
                "reduce_bands",
                (tuple(cast(value) for value in pixel.args[0]), *pixel.args[1:]),
                pixel.boolean,
            )
        raise AssertionError("unrecognized value-preserving Pixel operation")

    def _expression_with_double_structural_cast(self, rewrite):
        """Compile one structural cast rewrite under the shared depth limit."""
        depth = getattr(self, "_double_structural_depth", 0)
        if depth >= 96:
            fail("Earth Engine graph exceeds compilation limits")
        self._double_structural_depth = depth + 1
        try:
            return self.expression(rewrite)
        finally:
            self._double_structural_depth = depth

    def _expression(self, p):
        if p.op == "where":
            from .pixel_selection_graph import select_float64, where_float32

            if self.has_double_precision(p):
                return select_float64(self, Pixel("if", p.args), operation="where_select")
            return self.expression(where_float32(*p.args))
        if p.op == "integer_values":
            from .integer_values_graph import compile_integer_values_pixel

            return compile_integer_values_pixel(self, p)
        if (p.op in BOOLEAN_OPERATIONS or p.op in FLOAT64_ARITIES) and any(
                isinstance(value, Pixel) and self.has_double_precision(value)
                for value in p.args):
            from .integer_values_graph import compile_numeric_values_pixel

            return compile_numeric_values_pixel(self, p)
        if p.op.startswith("math_"):
            from .pixel_math_graph import compile_pixel_math

            return compile_pixel_math(self, p)
        if p.op == "classify":
            from .classification_graph import classify_pixel

            return classify_pixel(self, p)
        if p.op == "trained_classify":
            from .classification_graph import trained_classify_pixel

            return trained_classify_pixel(self, p)
        if p.op == "smile_rf_classify":
            from .smile_rf_graph import compile_smile_rf_pixel

            return compile_smile_rf_pixel(self, p)
        if p.op == "focal":
            from .focal_graph import compile_focal_pixel

            return compile_focal_pixel(self, p)
        if p.op == "convolve":
            from .convolve_graph import compile_convolve_pixel

            return compile_convolve_pixel(self, p)
        if p.op == "neighborhood":
            from .neighborhood_graph import compile_neighborhood_pixel

            return compile_neighborhood_pixel(self, p)
        if p.op == "terrain":
            from .terrain_graph import compile_terrain_pixel

            return compile_terrain_pixel(self, p)
        if p.op == "distance":
            from .distance_graph import compile_distance_pixel

            return compile_distance_pixel(self, p)
        if p.op == "fast_distance":
            from .fast_distance_graph import compile_fast_distance_pixel

            return compile_fast_distance_pixel(self, p)
        if p.op == "remap":
            from .remap_graph import compile_remap_pixel

            return compile_remap_pixel(self, p)
        if p.op == "constant":
            # GeoTrellis's scalar callback builder represents logical pixels as
            # 0/1; a Boolean false literal is not a numeric accept value there.
            value = p.args[0]
            return int(value) if isinstance(value, bool) else value, None, True
        if p.op == "band":
            source, name = p.args
            ref = self.node("filter_bands", data=self.source(source), bands=[name])
            return self.rename_band(ref, "v"), "v", True
        if p.op == "on_grid":
            from .constant_graph import materialize_constant
            return materialize_constant(self, p)
        if p.op == "clip":
            ref, label, timed = self.expression(p.args[0])
            if label is None: fail("Clipping an unbound constant image is unsupported")
            return self.node("mask_polygon", data=ref, mask=p.args[1]), label, timed
        if p.op in {"to_double", "to_float"}:
            if p.op == "to_double":
                rewrite = self._prepare_double_structural_rewrite(p.args[0])
                if rewrite is not None:
                    return self._expression_with_double_structural_cast(rewrite)
            ref, label, timed = self.expression(p.args[0])
            if label is None:
                if ref is None: return None, None, timed
                if p.op == "to_float":
                    import struct
                    return struct.unpack('!f', struct.pack('!f', ref))[0], None, timed
                return float(ref), None, timed
            return self.node("local_ee_" + p.op, data=ref), label, timed
        if p.op == "preserve_mask":
            ref, label, timed = self.expression(p.args[0])
            mask, _, mask_time = self.expression(Pixel("is_nodata", (p.args[1],), True))
            if timed != mask_time: fail("Mask dimensions do not match")
            return self.node("mask", data=ref, mask=mask), label, timed
        if p.op == "reduce_t":
            return reduce_time(self, p)
        if p.op in {"unmask", "unmask_constant"}:
            from .mask_graph import unmask
            return unmask(self, p)
        if p.op == "reduce_bands" and self.has_double_precision(p):
            from .reduction_graph import reduce_bands_double
            return reduce_bands_double(self, p)
        if (p.op == "if" and p.args[2].op == "constant"
                and p.args[2].args == (None,) and self.has_double_precision(p.args[1])):
            from .mask_graph import mask_float64

            return mask_float64(self, p.args[0], p.args[1])
        if p.op == "if" and self.has_double_precision(p):
            from .pixel_selection_graph import select_float64

            return select_float64(self, p)
        if p.op != "is_nodata" and self.has_double_precision(p):
            fail("Float64 pixel arithmetic is not supported by the pinned callback backend; apply toDouble() after arithmetic or explicitly toFloat() first")
        operands = p.args[0] if p.op == "reduce_bands" else p.args
        results = [self.expression(x) for x in operands]
        rasters = [(i, r) for i, r in enumerate(results) if r[1] is not None]
        if rasters:
            from .pixel_math_graph import bind_deferred_pixel_math, contains_pixel_math

            template = operands[rasters[0][0]]
            for index, result in enumerate(results):
                value, label, _ = result
                if label is None and isinstance(value, Pixel) and contains_pixel_math(value):
                    results[index] = self.expression(
                        bind_deferred_pixel_math(value, template)
                    )
            rasters = [(i, r) for i, r in enumerate(results) if r[1] is not None]
        if not rasters:
            from .pixel_math_graph import contains_pixel_math

            if contains_pixel_math(p):
                # Keep an unbound math subtree deferred until it meets a real
                # source grid. It must never acquire a fabricated global grid.
                return p, None, True
            # Only constant operations are computed here; arbitrary expressions
            # never pass through eval() or an interpreter supplied by the user.
            values = [r[0] for r in results]
            if p.op == "if": return values[1] if values[0] else values[2], None, True
            funcs = {"add": lambda: values[0]+values[1], "subtract": lambda: values[0]-values[1], "multiply": lambda: values[0]*values[1], "divide": lambda: values[0]/values[1], "power": lambda: scalar_power(values[0], values[1]), "eq": lambda: values[0]==values[1], "neq": lambda: values[0]!=values[1], "lt": lambda: values[0]<values[1], "lte": lambda: values[0]<=values[1], "gt": lambda: values[0]>values[1], "gte": lambda: values[0]>=values[1], "and": lambda: bool(values[0] and values[1]), "or": lambda: bool(values[0] or values[1]), "not": lambda: not values[0], "absolute": lambda: abs(values[0]),
                     "is_nodata": lambda: values[0] is None or not math.isfinite(values[0]),
                     "min2": lambda: min(values), "max2": lambda: max(values), "mod": lambda: math.fmod(*values),
                     "sqrt": lambda: math.sqrt(values[0]), "log": lambda: math.log(values[0]), "log10": lambda: math.log10(values[0]),
                     "exp": lambda: math.exp(values[0]), "round": lambda: math.floor(values[0]+.5),
                     "floor": lambda: math.floor(values[0]), "ceil": lambda: math.ceil(values[0]),
                     "sin": lambda: math.sin(values[0]), "cos": lambda: math.cos(values[0]), "tan": lambda: math.tan(values[0])}
            if p.op == "divide" and values[1] == 0: return 0, None, True
            if p.op not in funcs: fail("Unsupported unbound constant image expression")
            try:
                value = funcs[p.op]()
                return int(value) if isinstance(value, bool) else value, None, True
            except UnsupportedEEError: raise
            except (ArithmeticError, TypeError, ValueError): return None, None, True
        # Give every operand a distinct internal band. The callback then pairs
        # by explicit index; labels never implicitly decide band arithmetic.
        data = None
        callback = {}
        args = [r[0] for r in results]
        timed = rasters[0][1][2]
        for index, (position, (ref, _, has_time)) in enumerate(rasters):
            if has_time != timed: fail("Combining a temporal collection with a spatial image needs unsupported time broadcasting")
            ref = self.rename_band(ref, f"a{index}")
            data = ref if data is None else self.node("merge_cubes", cube1=data, cube2=ref)
            key = "a"+str(index)
            callback[key] = {"process_id": "array_element", "arguments": {"data": {"from_parameter": "data"}, "index": index}}
            args[position] = {"from_node": key}
        if p.op == "divide":
            # Official Image.divide / Number.divide explicitly return zero for
            # division by zero. Multiplying the numerator by zero preserves its
            # NoData mask instead of manufacturing a new valid pixel.
            callback["zero_denominator"] = {"process_id": "eq", "arguments": {"x": args[1], "y": 0}}
            callback["zero"] = {"process_id": "multiply", "arguments": {"x": args[0], "y": 0}}
            callback["quotient"] = {"process_id": "divide", "arguments": {"x": args[0], "y": args[1]}}
            process, op_args = "if", {"value": {"from_node": "zero_denominator"}, "accept": {"from_node": "zero"}, "reject": {"from_node": "quotient"}}
        elif p.op == "reduce_bands":
            reducer = p.args[1]
            # Some JVM aggregators reuse their first input tile as an
            # accumulator. A conditional may evaluate a callback reference
            # twice, so hand each aggregator fresh pixel tiles each time.
            safe_args = []
            for index, argument in enumerate(args):
                key = "copy"+str(index)
                callback[key] = {"process_id": "multiply", "arguments": {"x": argument, "y": 1}}
                safe_args.append({"from_node": key})
            process, op_args = reducer, {"data": safe_args, **({} if reducer == "count" else {"ignore_nodata": True})}
        elif p.op == "if":
            # The JVM callback requires a non-null accept operand. Invert a
            # null-accept conditional, preserving the same NoData branch.
            if args[1] is None:
                callback["inverted"] = {"process_id": "not", "arguments": {"x": args[0]}}
                process, op_args = "if", {"value": {"from_node": "inverted"}, "accept": args[2], "reject": None}
            else: process, op_args = "if", dict(zip(("value", "accept", "reject"), args))
        else: process, op_args = self.scalar_args(p.op, args[0], args[1] if len(args)>1 else None)
        if p.op == "reduce_bands" and p.args[1] in {"count", "sum"}:
            callback["reduced"] = {"process_id": process, "arguments": op_args}
            callback["valid_count"] = {"process_id": "count", "arguments": {"data": safe_args}}
            callback["has_values"] = {"process_id": "gt", "arguments": {"x": {"from_node": "valid_count"}, "y": 0}}
            process, op_args = "if", {"value": {"from_node": "has_values"}, "accept": {"from_node": "reduced"}, "reject": None}
        callback["result"] = {"process_id": process, "arguments": op_args, "result": True}
        result = self.node("reduce_dimension", data=data, dimension="bands", reducer={"process_graph": callback})
        return self.band_dimension(result, "v"), "v", timed
