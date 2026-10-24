"""Explicit routing from decoded Earth Engine invocations to small handlers."""
from __future__ import annotations

from . import collection_ops, filtering, image_ops, metadata_ops, value_ops
from .collection_metadata import handles_collection_metadata, invoke_collection_metadata
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
    if name in {"Terrain", "Terrain.products", "Terrain.slope", "Terrain.aspect", "Terrain.hillshade"}:
        from .image_terrain import invoke_terrain

        return invoke_terrain(translator, name, a)
    if name == "Image.neighborhoodToBands":
        from .neighborhood_bands import invoke_image_neighborhood_bands

        return invoke_image_neighborhood_bands(translator, a)
    if name == "Reducer.unweighted":
        from .neighborhood_reducer_plan import invoke_neighborhood_unweighted

        return invoke_neighborhood_unweighted(translator, a)
    if name.startswith("Kernel."):
        from .kernel_values import invoke_kernel

        return invoke_kernel(translator, name, a)
    if name == "Image.distance":
        from .image_distance import invoke_image_distance

        return invoke_image_distance(translator, a)
    from .image_fast_distance import FAST_DISTANCE_FUNCTIONS, invoke_image_fast_distance

    if name in FAST_DISTANCE_FUNCTIONS:
        return invoke_image_fast_distance(translator, a)
    from .image_convolve import CONVOLVE_FUNCTIONS, invoke_image_convolve

    if name in CONVOLVE_FUNCTIONS:
        return invoke_image_convolve(translator, a)
    from .image_focal import FOCAL_FUNCTIONS, invoke_image_focal

    if name in FOCAL_FUNCTIONS:
        return invoke_image_focal(translator, name, a)
    from .rf_explanation import (
        UNHANDLED,
        contains_runtime_explanation,
        has_runtime_explanation_argument,
        invoke_runtime_explanation,
        mark_runtime_explanation_seen,
        runtime_explanation_seen,
    )

    direct_runtime = has_runtime_explanation_argument(a)
    if direct_runtime:
        mark_runtime_explanation_seen(translator)
    if name == "Classifier.explain" or direct_runtime:
        result = invoke_runtime_explanation(
            translator, name, a, known_present=direct_runtime,
        )
        if result is not UNHANDLED:
            return result
    elif (runtime_explanation_seen(translator)
          and contains_runtime_explanation(a, translator)):
        result = invoke_runtime_explanation(
            translator, name, a, known_present=True,
        )
        if result is not UNHANDLED:
            return result
    if name == "DateRange" or name.startswith("DateRange."):
        from .date_ranges import invoke_date_range

        return invoke_date_range(translator, name, a)
    from .element_metadata_values import ELEMENT_METADATA_VALUE_METHODS, invoke_element_metadata_values
    from .feature_structure import FEATURE_STRUCTURE_METHODS, invoke_feature_structure
    from .geometry_structure import GEOMETRY_STRUCTURE_FUNCTIONS, invoke_geometry_structure

    if name in ELEMENT_METADATA_VALUE_METHODS:
        return invoke_element_metadata_values(translator, name, a)
    if name in FEATURE_STRUCTURE_METHODS:
        return invoke_feature_structure(translator, name, a)
    if name in GEOMETRY_STRUCTURE_FUNCTIONS:
        return invoke_geometry_structure(translator, name, a)
    if name == "Image.unmix":
        from .image_unmix import invoke_image_unmix

        return invoke_image_unmix(translator, name, a)
    if name in {"Image.rgbToHsv", "Image.hsvToRgb"}:
        from .image_color import invoke_image_color

        return invoke_image_color(translator, name, a)
    if name in {"Image.interpolate", "Image.polynomial"}:
        from .image_curves import invoke_image_curves

        return invoke_image_curves(translator, name, a)
    if name in {"Image.arrayDimensions", "Image.arrayPad"}:
        from .raster_array_preparation import invoke_raster_array_preparation

        return invoke_raster_array_preparation(translator, name, a)
    if name == "Image.arrayDotProduct":
        from .raster_array_dot import invoke_raster_array_dot

        return invoke_raster_array_dot(translator, name, a)
    if name in {"Image.regexpRename", "Image.slice", "Image.cat", "Image.float", "Image.double"}:
        from .image_band_preparation import invoke_image_band_preparation

        return invoke_image_band_preparation(translator, name, a)
    if name in {"Image.id", "Image.metadata"}:
        from .image_metadata_raster import invoke_image_metadata_raster

        return invoke_image_metadata_raster(translator, name, a)
    if name.startswith("AggregateFeatureCollection.") and name != "AggregateFeatureCollection.array":
        from .aggregate_statistics import invoke_aggregate_statistics

        return invoke_aggregate_statistics(translator, name, a)
    from .finite_reducer_leaves import handles_finite_reducer, invoke_finite_reducer

    if handles_finite_reducer(name):
        return invoke_finite_reducer(translator, name, a)
    from .statistical_reducer_leaves import STATISTICAL_REDUCER_NAMES, invoke_statistical_reducer

    if name in STATISTICAL_REDUCER_NAMES:
        return invoke_statistical_reducer(translator, name, a)
    from .composed_reducers import handles_composed_reducer, invoke_composed_reducer, is_reducer_spec

    if handles_composed_reducer(name):
        return invoke_composed_reducer(translator, name, a)
    if is_reducer_spec(a.get("reducer")):
        if name in {"Image.reduce", "ImageCollection.reduce"}:
            from .image_numeric_reducers import invoke_raster_numeric_reducer

            return invoke_raster_numeric_reducer(translator, name, a)
        if name == "Array.reduce":
            from .array_reductions import invoke_reduction

            return invoke_reduction(translator, name, a)
        if name == "Image.arrayReduce":
            from .raster_array_reductions import invoke_raster_reduction

            return invoke_raster_reduction(translator, name, a)
        if name == "List.reduce":
            from .composed_reducer_values import reduce_list

            translator.allowed(a, {"list", "reducer"})
            return reduce_list(translator, a.get("list"), a["reducer"])
        if name != "Collection.reduceColumns":
            fail("This composed Reducer context is unsupported; use an audited list, table, array or raster reduction")
    from .raster_array_bands import handles_array_bands, invoke_array_bands
    from .image_pixel_math import IMAGE_PIXEL_MATH_FUNCTIONS, invoke_image_pixel_math

    if name in IMAGE_PIXEL_MATH_FUNCTIONS:
        return invoke_image_pixel_math(translator, name, a)
    from .image_integer import IMAGE_INTEGER_FUNCTIONS, invoke_image_integer

    if name in IMAGE_INTEGER_FUNCTIONS:
        return invoke_image_integer(translator, name, a)
    if name == "Image.remap":
        from .image_remap import invoke_image_remap

        return invoke_image_remap(translator, a)
    if name == "Image.classify":
        from .raster_classification import invoke_image_classify

        return invoke_image_classify(translator, a)
    if name == "Image.sampleRegions":
        from .raster_sampling import invoke_sample_regions

        return invoke_sample_regions(translator, a)
    if name == "Image.sample":
        from .image_sampling import invoke_image_sample

        return invoke_image_sample(translator, a)
    if handles_array_bands(name, a):
        return invoke_array_bands(translator, name, a)
    if name in {"Classifier.confusionMatrix", "FeatureCollection.classify"}:
        from .classifier_features import invoke_classifier_features

        return invoke_classifier_features(translator, name, a)
    if name.startswith("Classifier."):
        from .ir import SmileRandomForest, TrainedSmileRandomForest

        if (name == "Classifier.smileRandomForest"
                or isinstance(a.get("classifier"),
                              (SmileRandomForest, TrainedSmileRandomForest))):
            from .smile_rf import invoke_classifier

            return invoke_classifier(translator, name, a)
        from .minimum_distance import invoke_classifier

        return invoke_classifier(translator, name, a)
    from .raster_array_dispatch import handles_raster_array, invoke_raster_array

    if handles_raster_array(name, a):
        return invoke_raster_array(translator, name, a)
    if name == "ImageCollection.toArrayPerBand":
        from .raster_collection_arrays import invoke_collection_array

        return invoke_collection_array(translator, name, a)
    if name == "ConfusionMatrix" or name.startswith("ConfusionMatrix."):
        from .confusion_values import invoke_confusion

        return invoke_confusion(translator, name, a)
    if name == "Collection.errorMatrix":
        from .feature_error_matrix import invoke_error_matrix

        return invoke_error_matrix(translator, name, a)
    if handles_collection_metadata(name, a):
        return invoke_collection_metadata(translator, name, a)
    if name == "List.reduce":
        from .list_reductions import invoke_list_reduce

        return invoke_list_reduce(translator, name, a)
    from .list_layout import LIST_LAYOUT_FUNCTIONS, invoke_list_layout

    if name in LIST_LAYOUT_FUNCTIONS:
        return invoke_list_layout(translator, name, a)
    from .table_reducers import TableReducer, handles_table_reducer, invoke_table_reducer, invoke_reduce_columns

    if handles_table_reducer(name):
        return invoke_table_reducer(translator, name, a)
    if name == "Collection.reduceColumns":
        from .ir import Reducer

        if isinstance(a.get("reducer"), Reducer) or is_reducer_spec(a.get("reducer")):
            from .composed_reducer_tables import reduce_columns

            return reduce_columns(translator, a, a["reducer"])
        return invoke_reduce_columns(translator, name, a)
    if (name == "ImageCollection.reduce" and isinstance(a.get("reducer"), TableReducer)
            and a["reducer"].name == "linearFit"):
        from .raster_linear_fit import invoke_raster_linear_fit

        return invoke_raster_linear_fit(translator, name, a)
    if (name == "ImageCollection.reduce" and isinstance(a.get("reducer"), TableReducer)
            and a["reducer"].name == "linearRegression"):
        from .raster_linear_regression import invoke_raster_linear_regression

        return invoke_raster_linear_regression(translator, name, a)
    if isinstance(a.get("reducer"), TableReducer) and name in {
        "Image.reduce", "Image.reduceRegion", "ImageCollection.reduce",
    }:
        fail("This regression Reducer currently supports static table reduceColumns only")
    from .feature_table_selection import (
        handles_feature_table_selection, invoke_feature_table_selection,
    )

    if handles_feature_table_selection(name, a):
        return invoke_feature_table_selection(translator, name, a)
    from .nested_collections import (
        handles_nested_collection_operation, invoke_nested_collection_operation,
    )

    if handles_nested_collection_operation(name, a):
        return invoke_nested_collection_operation(translator, name, a)
    from .feature_ops import handles_feature, invoke_feature

    if handles_feature(name, a):
        return invoke_feature(translator, name, a)
    if name == "Number.format":
        from .number_format import format_number

        return format_number(translator, a)
    if name == "Number.parse":
        from .number_parse import invoke_number_parse

        return invoke_number_parse(translator, name, a)
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
        from .date_calendar import SUPPORTED_DATE_CALENDAR_FUNCTIONS, invoke_date_calendar
        from ...ee_dates import SUPPORTED_DATE_FUNCTIONS, invoke_date

        if name in SUPPORTED_DATE_CALENDAR_FUNCTIONS:
            return invoke_date_calendar(translator, name, a)
        if name in SUPPORTED_DATE_FUNCTIONS:
            return invoke_date(translator, name, a)
    if name.startswith("Number."):
        from .integer_aliases import canonical_integer_name
        from ...ee_integer import SUPPORTED_INTEGER_FUNCTIONS, invoke_integer

        integer_name = canonical_integer_name(name)
        if integer_name in SUPPORTED_INTEGER_FUNCTIONS:
            return invoke_integer(translator, integer_name, a)
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
