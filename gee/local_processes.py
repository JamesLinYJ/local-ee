"""Specifications for the small, source-controlled native process extensions."""
import math


LOCAL_PROCESSES = frozenset({"local_ee_to_double", "local_ee_to_float",
                             "local_ee_constant_on_grid", "local_ee_unmask"})
CUBE = {"type": "object", "subtype": "raster-cube"}


def validate_local_process(name, arguments, depth):
    """Extensions only accept bounded literals and canonical top-level cubes."""
    required = {"data"}
    if name in {"local_ee_unmask", "local_ee_constant_on_grid"}:
        required.add("value")
    allowed = required | ({"same_footprint"} if name == "local_ee_unmask" else set())
    if depth != 0 or not required <= set(arguments) <= allowed:
        raise ValueError("Local EE extensions require top-level cube references and supported arguments")
    cubes = [arguments["data"]]
    if name == "local_ee_unmask":
        cubes.append(arguments["value"])
        if not isinstance(arguments.get("same_footprint", True), bool):
            raise ValueError("Local EE same_footprint must be a boolean")
    if any(not isinstance(value, dict) or set(value) != {"from_node"} for value in cubes):
        raise ValueError("Local EE extensions require top-level cube references")
    if name == "local_ee_constant_on_grid":
        value = arguments["value"]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or abs(value) > 2**53 or not math.isfinite(value)):
            raise ValueError("Local EE grid constant requires a finite exact Float64 number within 2^53")


def process_spec(name):
    if name in {"local_ee_to_double", "local_ee_to_float"}:
        return type_conversion_spec(name)
    descriptions = {
        "local_ee_constant_on_grid": "Create valid Float64 constants on a bounded template grid, including missing tiles. Does not expand its extent; runtime key/cell budgets apply.",
        "local_ee_unmask": "Select valid input cells, otherwise replacement cells, preserving NaN masks and Float64 precision. Requires aligned single-band cubes and identical observation instants; rejects implicit reprojection or time broadcasting.",
    }
    parameters = [{"name": "data", "description": "Input raster cube", "schema": CUBE}]
    parameters.append({"name": "value", "description": "Replacement cube" if name == "local_ee_unmask" else "Finite numeric constant",
                       "schema": CUBE if name == "local_ee_unmask" else {"type": "number", "minimum": -(2**53), "maximum": 2**53}})
    if name == "local_ee_unmask":
        parameters.append({"name": "same_footprint", "description": "Retain input keys and extent; polygon footprints are masked by the EE compiler", "schema": {"type": "boolean"}, "optional": True, "default": True})
    return {"id": name, "summary": descriptions[name].split(".")[0], "description": descriptions[name],
            "experimental": True, "categories": ["cubes"], "parameters": parameters,
            "returns": {"description": "Float64 raster cube", "schema": CUBE}}


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
