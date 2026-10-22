"""Public pure EE decoder/compiler boundary; no script execution or networking."""
import json

from .ir import (ImageSequence, Image, Collection, Region, Function, ParsedExpression,
                 Filter, Reducer, UnsupportedEEError, fail)
from .decoder import Translator
from .graph import Graph
from .public_values import public_result
from .join_ops import Join
from .table_reducers import TableReducer
from .inner_join import InnerJoin


def compile_expression(expression, catalog, items, options=None):
    """Compile one legacy ee.Serializer.encode value; no network or execution.

    Internal load_collection._gee_item_ids must be validated and materialized
    only by the trusted backend; this function does not resolve file paths.
    """
    if isinstance(expression, str):
        try: expression = json.loads(expression)
        except json.JSONDecodeError as exc: raise UnsupportedEEError("Expected serialized Earth Engine JSON") from exc
    if len(json.dumps(expression)) > 1000000: fail("Serialized Earth Engine expression exceeds 1 MB")
    translator = Translator(catalog, items, options)
    try:
        value = translator.evaluate(expression)
        from .raster_array_core import RasterArrayImage

        if isinstance(value, RasterArrayImage):
            fail("Array image output requires arrayFlatten or arrayGet; direct array raster export is unsupported")
        from .raster_array_bands import RasterArrayBands

        if isinstance(value, RasterArrayBands):
            fail("Multiple array bands require select then arrayFlatten or arrayGet; direct array raster export is unsupported")
        from .confusion_values import StaticConfusionMatrix

        if isinstance(value, StaticConfusionMatrix):
            fail("ConfusionMatrix output requires array(), order(), accuracy() or kappa(); direct server-object JSON is unsupported")
        from .minimum_distance import StaticMinimumDistance

        if isinstance(value, StaticMinimumDistance):
            fail("Classifier output requires schema(), confusionMatrix() accessors or FeatureCollection.classify; direct server-object JSON is unsupported")
        if isinstance(value, ImageSequence):
            return public_result({"kind":"collection", "bands":[n for n,_ in value.images[0].bands] if value.images else [],
                    "source_item_ids":[im.props.get("system:index",str(i)) for i,im in enumerate(value.images)],
                    "features":[{"type":"Image","id":im.props.get("system:index",str(i)),"properties":im.props,
                                 "bands":[{"id":n} for n,_ in im.bands]} for i,im in enumerate(value.images)],
                    "has_time_dimension":True,"warnings":translator.warnings,"properties":{}})
        if isinstance(value, (Image, Collection)):
            graph = Graph(translator)
            image = value.image if isinstance(value, Collection) else value
            ref, timed = graph.image(image)
            return public_result({"kind": "collection" if isinstance(value, Collection) else "image",
                    "process_graph": graph.finish(ref), "bands": [n for n, _ in image.bands],
                    "properties": image.props, "warnings": translator.warnings,
                    "has_time_dimension": timed, "source_item_ids": list(dict.fromkeys(i for source in graph.sources for i in source.ids))})
        if isinstance(value, Region):
            opts = {k: v for k, v in value.options.items() if k in {"region", "scale", "crs"}}
            translator.options = opts
            graph = Graph(translator)
            ref, timed = graph.image(value.image)
            if timed: fail("reduceRegion requires a single Image, not a time-dependent collection")
            reducer = graph.callback(value.reducer.name, {"data": {"from_parameter": "data"}, **({} if value.reducer.name == "count" else {"ignore_nodata": True})})
            ref = graph.node("aggregate_spatial", data=ref, geometries=value.geometry, reducer=reducer)
            return public_result({"kind": "region", "process_graph": graph.finish(ref), "bands": [n for n, _ in value.image.bands], "warnings": translator.warnings, "reducer": value.reducer.name,
                    "geometry": value.geometry, "grid_options": value.options})
        if isinstance(value, (Function, ParsedExpression, Filter, Reducer, Join, InnerJoin, TableReducer)):
            fail("A function/filter/reducer/join is not a computable output value")
        # Ensure no internal class or non-finite number crosses the API boundary.
        return public_result({"kind": "value", "value": value, "warnings": translator.warnings})
    except UnsupportedEEError:
        raise
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, RecursionError, OverflowError) as exc:
        raise UnsupportedEEError(f"Malformed or unsupported Earth Engine expression: {exc}") from exc
