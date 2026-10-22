"""Route typed array images without exposing their scalar storage as bands."""
from __future__ import annotations

from dataclasses import replace

from .array_core import StaticArray
from .ir import Image, fail
from .metadata_ops import METADATA_HANDLERS, invoke_metadata
from .raster_array_core import RasterArrayImage
from .raster_array_concatenation import RASTER_CONCATENATION_FUNCTIONS, invoke_raster_concatenation
from .raster_array_layout import RASTER_ARRAY_LAYOUT_FUNCTIONS, invoke_raster_layout
from .raster_array_reductions import RASTER_ARRAY_REDUCTION_FUNCTIONS, invoke_raster_reduction
from .raster_array_reshape import RASTER_RESHAPE_FUNCTIONS, invoke_raster_reshape
from .raster_array_values import RASTER_ARRAY_VALUE_FUNCTIONS, invoke_raster_value
from .raster_matrix_solve import RASTER_MATRIX_FUNCTIONS, invoke_raster_matrix


_SHARED_SCALAR_NAMES = {"Image.constant", "Image.add", "Image.subtract", "Image.multiply", "Image.divide", "Image.toFloat"}
_METADATA_ARGUMENTS = {
    "Element.get": {"object", "property"},
    "Image.get": {"object", "image", "property"},
    "Element.propertyNames": {"element"},
    "Element.set": {"object", "key", "value"},
    "Element.setMulti": {"object", "properties"},
    "Element.copyProperties": {"destination", "source", "properties", "exclude"},
    "Image.copyProperties": {"destination", "source", "properties", "exclude"},
}


def handles_raster_array(name, arguments):
    if name in (RASTER_ARRAY_LAYOUT_FUNCTIONS | RASTER_ARRAY_REDUCTION_FUNCTIONS
                | RASTER_MATRIX_FUNCTIONS | RASTER_RESHAPE_FUNCTIONS | RASTER_CONCATENATION_FUNCTIONS
                | (RASTER_ARRAY_VALUE_FUNCTIONS - _SHARED_SCALAR_NAMES)):
        return True
    if name == "Image.constant" and isinstance(arguments.get("value"), StaticArray):
        return True
    image_operation = name == "Image" or name.startswith("Image.") or name in METADATA_HANDLERS
    return image_operation and any(isinstance(value, RasterArrayImage) for value in arguments.values())


def invoke_raster_array(translator, name, arguments):
    if name in RASTER_CONCATENATION_FUNCTIONS:
        return invoke_raster_concatenation(translator, name, arguments)
    if name in RASTER_RESHAPE_FUNCTIONS:
        return invoke_raster_reshape(translator, name, arguments)
    if name in RASTER_MATRIX_FUNCTIONS:
        return invoke_raster_matrix(translator, name, arguments)
    if name in RASTER_ARRAY_LAYOUT_FUNCTIONS:
        return invoke_raster_layout(translator, name, arguments)
    if name in RASTER_ARRAY_REDUCTION_FUNCTIONS:
        return invoke_raster_reduction(translator, name, arguments)
    if name in RASTER_ARRAY_VALUE_FUNCTIONS:
        return invoke_raster_value(translator, name, arguments)
    if name == "Image":
        translator.allowed(arguments, {"input"})
        if not isinstance(arguments.get("input"), RasterArrayImage):
            fail("Image array cast requires a typed array image")
        return arguments["input"]
    if name == "Image.bandNames":
        translator.allowed(arguments, {"image"})
        return [arguments["image"].name]
    if name == "Image.rename":
        translator.allowed(arguments, {"input", "names"})
        array, names = arguments["input"], arguments["names"]
        if (not isinstance(array, RasterArrayImage) or not isinstance(names, list)
                or len(names) != 1 or not isinstance(names[0], str)
                or not names[0] or len(names[0]) > 256):
            fail("An array image rename requires one nonempty name of at most 256 characters")
        return replace(array, name=names[0])
    if name in METADATA_HANDLERS:
        translator.allowed(arguments, _METADATA_ARGUMENTS[name])
        # Metadata belongs to the logical image, never its internal cell list.
        destination = arguments.get("destination", arguments.get("object"))
        image_parameters = {"object", "image", "element", "destination", "source"}
        converted = {key: value.image if key in image_parameters and isinstance(value, RasterArrayImage) else value
                     for key, value in arguments.items()}
        result = invoke_metadata(translator, name, converted)
        if isinstance(result, Image) and isinstance(destination, RasterArrayImage):
            return replace(destination, image=result)
        return result
    fail(f"Unsupported operation on a fixed-shape array image: {name}")
