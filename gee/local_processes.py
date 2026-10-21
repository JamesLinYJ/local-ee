"""Specifications for the small, source-controlled native process extensions."""


def type_conversion_spec(name):
    types = {"local_ee_to_double": "Float64", "local_ee_to_float": "Float32"}
    target = types[name]
    return {
        "id": name,
        "summary": "Convert raster cells to " + target,
        "description": "Local EE native extension. Converts physical cell type and preserves NoData, bands, dimensions and grid. Only top-level cube references are accepted. Does not make downstream callbacks precision-preserving.",
        "experimental": True,
        "categories": ["cubes"],
        "parameters": [{"name": "data", "description": "Input raster cube", "schema": {"type": "object", "subtype": "raster-cube"}}],
        "returns": {"description": target + " raster cube", "schema": {"type": "object", "subtype": "raster-cube"}},
    }
