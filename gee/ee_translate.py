"""Backward-compatible imports for the modular Earth Engine compiler.

Implementation lives in ``gee.compat.earthengine``. This module keeps callers
and saved integrations stable; it contains no interpreter or raster algorithms.
"""
from .compat.earthengine.ir import (
    UnsupportedEEError, Source, Pixel, Image, Collection, ImageSequence, Function,
    ParsedExpression, Filter, Reducer, Region, fail, const, integer, static_truth,
    _substitute, rebind, as_image, pairs, binary, unary,
)
from .compat.earthengine.date_values import millis, time_of, utc_date, format_date
from .compat.earthengine.capabilities import SUPPORTED_FUNCTIONS, get_capabilities
from .compat.earthengine.decoder import Translator
from .compat.earthengine.graph import Graph
from .compat.earthengine.compile import compile_expression

__all__ = [
    "UnsupportedEEError", "Source", "Pixel", "Image", "Collection", "ImageSequence",
    "Function", "ParsedExpression", "Filter", "Reducer", "Region", "Translator",
    "Graph", "compile_expression", "SUPPORTED_FUNCTIONS", "get_capabilities",
    "fail", "const", "integer", "static_truth", "_substitute", "rebind", "as_image",
    "pairs", "binary", "unary", "millis", "time_of", "utc_date", "format_date",
]
