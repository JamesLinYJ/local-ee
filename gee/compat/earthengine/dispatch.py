"""Explicit routing from decoded Earth Engine invocations to small handlers."""
from __future__ import annotations

from . import collection_ops, filtering, image_ops, metadata_ops, value_ops
from .ir import ImageSequence, fail


_SIMPLE_ARGUMENTS = {
    "Image.constant": {"value"},
    "Image.bandNames": {"image"},
    "Date.millis": {"date"},
    "Collection.size": {"collection"},
    "Collection.first": {"collection"},
}
_METADATA_ARGUMENTS = {
    "Element.get": {"object", "property"},
    "Image.get": {"object", "image", "property"},
    "Element.propertyNames": {"element"},
    "Element.set": {"object", "key", "value"},
    "Element.setMulti": {"object", "properties"},
}


def invoke(translator, name, arguments):
    """Dispatch in the same precedence order as the legacy translator."""
    a = arguments
    from .raster_array_dispatch import handles_raster_array, invoke_raster_array

    if handles_raster_array(name, a):
        return invoke_raster_array(translator, name, a)
    if name == "ConfusionMatrix" or name.startswith("ConfusionMatrix."):
        from .confusion_values import invoke_confusion

        return invoke_confusion(translator, name, a)
    if name == "Collection.errorMatrix":
        from .feature_error_matrix import invoke_error_matrix

        return invoke_error_matrix(translator, name, a)
    from .table_reducers import TableReducer, handles_table_reducer, invoke_table_reducer, invoke_reduce_columns

    if handles_table_reducer(name):
        return invoke_table_reducer(translator, name, a)
    if name == "Collection.reduceColumns":
        return invoke_reduce_columns(translator, name, a)
    if (name == "ImageCollection.reduce" and isinstance(a.get("reducer"), TableReducer)
            and a["reducer"].name == "linearFit"):
        from .raster_linear_fit import invoke_raster_linear_fit

        return invoke_raster_linear_fit(translator, name, a)
    if isinstance(a.get("reducer"), TableReducer) and name in {
        "Image.reduce", "Image.reduceRegion", "ImageCollection.reduce",
    }:
        fail("This regression Reducer currently supports static table reduceColumns only")
    from .feature_ops import handles_feature, invoke_feature

    if handles_feature(name, a):
        return invoke_feature(translator, name, a)
    if name == "Number.format":
        from .number_format import format_number

        return format_number(translator, a)
    if name == "Array" or name.startswith("Array."):
        from .array_values import invoke_array

        return invoke_array(translator, name, a)
    if name in {"Join.inner", "Join.apply"}:
        from .inner_join import InnerJoin, apply_inner, construct_inner

        if name == "Join.inner":
            return construct_inner(translator, a)
        if isinstance(a.get("join"), InnerJoin):
            return apply_inner(translator, a)
    if name.startswith("Join."):
        from .join_ops import invoke_join

        return invoke_join(translator, name, a)
    if name == "Collection.map" and a.get("dropNulls") is not None and not isinstance(a["dropNulls"], bool):
        fail("Collection.map dropNulls must be a boolean")
    if name.startswith("Date."):
        from ...ee_dates import SUPPORTED_DATE_FUNCTIONS, invoke_date

        if name in SUPPORTED_DATE_FUNCTIONS:
            return invoke_date(translator, name, a)
    if name.startswith("Number."):
        from ...ee_integer import SUPPORTED_INTEGER_FUNCTIONS, invoke_integer

        if name in SUPPORTED_INTEGER_FUNCTIONS:
            return invoke_integer(translator, name, a)
    if name == "ImageCollection.qualityMosaic":
        translator.allowed(a, {"collection", "qualityBand"})
        from ...ee_quality import quality_mosaic

        return quality_mosaic(translator, a["collection"], a["qualityBand"])
    if name == "Image.unmask":
        from ...ee_masks import invoke_mask
        return invoke_mask(translator, name, a)
    if name in {"ImageCollection.fromImages", "ImageCollection.merge"} or isinstance(a.get("collection"), ImageSequence):
        from ...ee_collections import invoke_sequence

        return invoke_sequence(translator, name, a)
    if name in _SIMPLE_ARGUMENTS:
        translator.allowed(a, _SIMPLE_ARGUMENTS[name])
    if name in _METADATA_ARGUMENTS:
        translator.allowed(a, _METADATA_ARGUMENTS[name])
    if collection_ops.handles_collection(name):
        return collection_ops.invoke_collection(translator, name, a)
    if name.startswith("Filter."):
        return filtering.invoke_filter(translator, name, a)
    if name in metadata_ops.METADATA_HANDLERS:
        return metadata_ops.invoke_metadata(translator, name, a)
    if image_ops.handles_image(name):
        return image_ops.invoke_image(translator, name, a)
    if value_ops.handles_value(name):
        return value_ops.invoke_value(translator, name, a)
    fail(f"Unsupported Earth Engine algorithm: {name}")
