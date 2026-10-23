"""Specifications for the small, source-controlled native process extensions."""
import math

from .smile_rf_processes import RF_PROCESSES, rf_process_spec, validate_rf_process
from .rf_validation_processes import (
    VALIDATION_PROCESSES, validate_validation_process, validation_process_spec,
)


LOCAL_PROCESSES = frozenset({
    "local_ee_to_double", "local_ee_to_float", "local_ee_constant_on_grid",
    "local_ee_unmask", "local_ee_drop_single_time", "local_ee_reduce_bands",
    "local_ee_table", "local_ee_minimum_distance",
    "local_ee_sample_regions", "local_ee_train_minimum_distance",
    "local_ee_remap", "local_ee_sample_table_op", "local_ee_pixel_math", "local_ee_integer_values", "local_ee_focal", "local_ee_convolve",
    "local_ee_neighborhood", "local_ee_terrain", "local_ee_distance", "local_ee_fast_distance_transform",
}) | RF_PROCESSES | VALIDATION_PROCESSES
CUBE = {"type": "object", "subtype": "raster-cube"}
from .reduction_contract import EE_BAND_REDUCERS


def validate_local_process(name, arguments, depth, *, node_context=None):
    """Extensions only accept bounded literals and canonical top-level cubes."""
    if name in VALIDATION_PROCESSES:
        validate_validation_process(name, arguments, depth, node_context)
        return
    if name in RF_PROCESSES:
        validate_rf_process(name, arguments, depth, node_context)
        return
    if name == "local_ee_table":
        raise ValueError("Inline tables require a complete top-level table-only CSV graph")
    if not isinstance(arguments, dict):
        raise ValueError("Local EE extensions require an argument object")
    required = {"data"}
    if name in {"local_ee_unmask", "local_ee_constant_on_grid"}:
        required.add("value")
    if name == "local_ee_reduce_bands":
        required.add("reducer")
    if name == "local_ee_pixel_math":
        required.add("operation")
    if name == "local_ee_minimum_distance":
        required.add("model")
    if name in {"local_ee_sample_regions", "local_ee_train_minimum_distance",
                "local_ee_remap", "local_ee_sample_table_op", "local_ee_focal", "local_ee_convolve",
                "local_ee_neighborhood", "local_ee_terrain", "local_ee_distance", "local_ee_fast_distance_transform", "local_ee_integer_values"}:
        required.add("spec")
    allowed = required | ({"same_footprint"} if name == "local_ee_unmask" else set())
    if depth != 0 or not required <= set(arguments) <= allowed:
        raise ValueError("Local EE extensions require top-level cube references and supported arguments")
    cubes = [arguments["data"]]
    if name == "local_ee_unmask":
        cubes.append(arguments["value"])
        if not isinstance(arguments.get("same_footprint", True), bool):
            raise ValueError("Local EE same_footprint must be a boolean")
    if any(not isinstance(value, dict) or set(value) != {"from_node"}
           or type(value['from_node']) is not str or not value['from_node'] for value in cubes):
        raise ValueError("Local EE extensions require top-level cube references")
    if name == "local_ee_minimum_distance":
        from .compat.earthengine.classifier_model import model_validation_work, validate_model

        model = arguments["model"]
        if type(model) is dict and set(model) == {"from_node"}:
            producer = node_context.get(model["from_node"], {}) if type(node_context) is dict and type(model["from_node"]) is str else {}
            if producer.get("process_id") != "local_ee_train_minimum_distance":
                raise ValueError("Dynamic classifier models require an audited sampled-training producer")
        else:
            if model_validation_work(model) > 50_000:
                raise ValueError("Raster classifier model exceeds the 50000-step work budget")
            validate_model(model)
    if name in {"local_ee_sample_regions", "local_ee_train_minimum_distance"}:
        from .sampling_spec import decode_sampling_spec, decode_training_spec

        decoder = decode_sampling_spec if name == "local_ee_sample_regions" else decode_training_spec
        decoder(arguments["spec"])
    if name == "local_ee_focal":
        from .focal_spec import decode_focal_spec

        decode_focal_spec(arguments["spec"])
    if name == "local_ee_convolve":
        from .convolve_spec import decode_convolve_spec

        decode_convolve_spec(arguments["spec"])
    if name == "local_ee_neighborhood":
        from .neighborhood_spec import decode_neighborhood_spec

        decode_neighborhood_spec(arguments["spec"])
    if name == "local_ee_fast_distance_transform":
        from .fast_distance_spec import decode_fast_distance_spec

        decode_fast_distance_spec(arguments["spec"])
    if name == "local_ee_distance":
        from .distance_spec import decode_distance_spec

        decode_distance_spec(arguments["spec"])
    if name == "local_ee_terrain":
        from .terrain_spec import decode_terrain_spec

        decode_terrain_spec(arguments["spec"])
    if name == "local_ee_remap":
        from .remap_spec import decode_remap_spec

        decode_remap_spec(arguments["spec"])
    if name == "local_ee_sample_table_op":
        from .sample_table_spec import decode_sample_operation

        decode_sample_operation(arguments["spec"])
    if name == "local_ee_constant_on_grid":
        value = arguments["value"]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or abs(value) > 2**53 or not math.isfinite(value)):
            raise ValueError("Local EE grid constant requires a finite exact Float64 number within 2^53")
    if name == "local_ee_reduce_bands":
        reducer = arguments["reducer"]
        if type(reducer) is not str or reducer not in EE_BAND_REDUCERS:
            raise ValueError("Local EE band reducer must be one of the supported reducer names")
    if name == "local_ee_pixel_math":
        from .pixel_math_contract import validate_pixel_math_operation

        validate_pixel_math_operation(arguments["operation"])
    if name == "local_ee_integer_values":
        from .integer_values_spec import decode_integer_values_spec

        decode_integer_values_spec(arguments["spec"])


def process_spec(name):
    if name == "local_ee_integer_values":
        from .integer_values_spec import integer_values_process_spec

        return integer_values_process_spec()
    if name == "local_ee_fast_distance_transform":
        from .fast_distance_spec import fast_distance_process_spec

        return fast_distance_process_spec()
    if name == "local_ee_distance":
        from .distance_spec import distance_process_spec

        return distance_process_spec()
    if name == "local_ee_terrain":
        from .terrain_spec import terrain_process_spec

        return terrain_process_spec()
    if name == "local_ee_neighborhood":
        from .neighborhood_spec import neighborhood_process_spec

        return neighborhood_process_spec()
    if name == "local_ee_convolve":
        from .convolve_spec import convolve_process_spec

        return convolve_process_spec()
    if name == "local_ee_focal":
        from .focal_spec import focal_process_spec

        return focal_process_spec()
    if name == "local_ee_pixel_math":
        return _pixel_math_spec()
    if name in VALIDATION_PROCESSES:
        return validation_process_spec(name)
    if name in RF_PROCESSES:
        return rf_process_spec(name)
    if name == "local_ee_table":
        from .table_graph import table_process_spec
        return table_process_spec()
    if name in {"local_ee_to_double", "local_ee_to_float"}:
        return type_conversion_spec(name)
    if name == "local_ee_minimum_distance":
        return _classification_spec(name)
    if name in {"local_ee_sample_regions", "local_ee_train_minimum_distance"}:
        return _sampling_process_spec(name)
    if name in {"local_ee_remap", "local_ee_sample_table_op"}:
        return _sample_preparation_spec(name)
    descriptions = {
        "local_ee_constant_on_grid": "Create valid Float64 constants on a bounded template grid, including missing tiles. Does not expand its extent; runtime key/cell budgets apply.",
        "local_ee_unmask": "Select valid input cells, otherwise replacement cells, preserving NaN masks and Float64 precision. Requires aligned single-band cubes and identical observation instants; rejects implicit reprojection or time broadcasting.",
        "local_ee_drop_single_time": "Convert a raster cube with exactly one observation instant to a spatial cube, removing the temporal dimension while preserving band names and grid.",
        "local_ee_reduce_bands": "Reduce ordered raster bands with a supported reducer in Float64, returning one band named v while preserving time and grid. All-NoData cells remain NaN.",
    }
    parameters = [{"name": "data", "description": "Input raster cube", "schema": CUBE}]
    if name == "local_ee_drop_single_time":
        return _cube_process_spec(name, descriptions[name], parameters)
    if name == "local_ee_reduce_bands":
        parameters.append({"name": "reducer", "description": "Reducer applied across bands in source order",
                           "schema": {"type": "string", "enum": sorted(EE_BAND_REDUCERS)}})
        return _cube_process_spec(name, descriptions[name], parameters)
    parameters.append({"name": "value", "description": "Replacement cube" if name == "local_ee_unmask" else "Finite numeric constant",
                       "schema": CUBE if name == "local_ee_unmask" else {"type": "number", "minimum": -(2**53), "maximum": 2**53}})
    if name == "local_ee_unmask":
        parameters.append({"name": "same_footprint", "description": "Retain input keys and extent; polygon footprints are masked by the EE compiler", "schema": {"type": "boolean"}, "optional": True, "default": True})
    return _cube_process_spec(name, descriptions[name], parameters)


def _cube_process_spec(name, description, parameters):
    return {"id": name, "summary": description.split(".")[0], "description": description,
            "experimental": True, "categories": ["cubes"], "parameters": parameters,
            "returns": {"description": "Float64 raster cube", "schema": CUBE}}


def _pixel_math_spec():
    from .pixel_math_contract import PIXEL_MATH_OPERATIONS

    return {
        "id": "local_ee_pixel_math", "experimental": True,
        "summary": "Bounded Float32 scientific pixel math",
        "description": (
            "Top-level raster reference with ordered x or x,y input bands and one v output. "
            "Grid, observation keys and spatial/temporal dimensions are preserved. "
            "Actual Float32 finite inputs only; NaN masks, real-domain errors, nonfinite "
            "and Float32-overflow results become NoData. Existing grid/key/cell limits "
            "and 67108864 pixel-operation work limit apply. Google parity is unverified."
        ),
        "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "Ordered Float32 operand bands", "schema": CUBE},
            {"name": "operation", "description": "Fixed native math operation",
             "schema": {"type": "string", "enum": sorted(PIXEL_MATH_OPERATIONS)}},
        ],
        "returns": {"description": "One Float32 NoData band v", "schema": CUBE},
    }


def _sample_preparation_spec(name):
    raster = name == "local_ee_remap"
    schema = CUBE if raster else {"type": "object", "subtype": "vector-cube"}
    return {
        "id": name, "experimental": True,
        "summary": "Exact finite numeric raster remapping" if raster else "Transform real sampled features",
        "description": (
            "Top-level canonical data reference and bounded canonical JSON specification. "
            + ("One source band,0..256 unique finite numeric keys, exact actual Float32/Float64 comparison; "
               "selected NoData stays masked, unmatched values use a finite default or mask. "
               "Output physically Float64 with NaN NoData and band v; existing cube/time/grid/key/cell "
               "and67108864 pixel-key work limits remain. No Google dtype equivalence claim."
               if raster else
               "Actual sampled table or its audited operation producer only. Filter/unsorted limit "
               "retain current columns, order, IDs, properties and optional center geometry. "
               "random_column adds or overwrites an ordinary numeric column with tracked schema; "
               "typed row keys and signed64 seed use local deterministic SHA256 uniform or Box-Muller normal. "
               "Missing/null keys and reserved output columns reject; Google RNG parity is unverified. "
               "At most16 operations,64 predicate nodes/depth16 and shared50000 runtime work; "
               "base sampler row/cell/byte limits apply before operations. Dry-run has no rows. "
               "Sorting, arbitrary computed columns and executable callbacks reject.")),
        "categories": ["cubes" if raster else "vector-cubes"],
        "parameters": [
            {"name": "data", "description": "One-band raster cube" if raster else "Audited sampled table", "schema": schema},
            {"name": "spec", "description": "Canonical version1 specification", "schema": {"type": "string"}},
        ],
        "returns": {"description": "Float64 raster cube" if raster else "Actual filtered sampled table", "schema": schema},
    }


def _classification_spec(name):
    description = (
        "Classify schema-ordered finite raster bands against exact rational class centers. "
        "Version 1 supports Euclidean, Manhattan and cosine, k=1 CLASSIFICATION, "
        "1..8 unique flat schema names and 1..64 sorted labels in 0..63. "
        "Input band names and order must equal the schema. Actual Float32/Float64 values "
        "are preserved; output is one Int32 NoData band v with input grid and time. "
        "Any selected NoData masks the pixel; valid infinity, nearest-class ties and "
        "cosine zero vectors reject. Reduced center fractions use canonical decimal "
        "string pairs, at most 700 characters/2200 bits each and finite Float64 magnitude. "
        "Shared grid/key/cell limits and 67108864 pixel-class-band operations apply. "
        "Full Spark batch execution and Google numerical equivalence remain unverified."
    )
    return {
        "id": name, "summary": "Exact bounded minimum-distance raster classification",
        "description": description, "experimental": True, "categories": ["cubes"],
        "parameters": [
            {"name": "data", "description": "Schema-ordered input raster cube", "schema": CUBE},
            {"name": "model", "description": "Strict version-1 exact rational model",
             "schema": {"type": "object", "additionalProperties": False,
                        "required": ["version", "metric", "schema", "labels", "centers"],
                        "properties": {
                            "version": {"type": "integer", "enum": [1]},
                            "metric": {"type": "string", "enum": ["euclidean", "manhattan", "cosine"]},
                            "schema": {"type": "array", "minItems": 1, "maxItems": 8,
                                       "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
                            "labels": {"type": "array", "minItems": 1, "maxItems": 64,
                                       "uniqueItems": True, "items": {"type": "integer", "minimum": 0, "maximum": 63}},
                            "centers": {"type": "array", "minItems": 1, "maxItems": 64},
                        }}},
        ],
        "returns": {"description": "Singleton integer classification band v with Int32 NoData", "schema": CUBE},
    }


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


def _sampling_process_spec(name):
    sample = name == "local_ee_sample_regions"
    return {
        "id": name, "experimental": True,
        "summary": "Sample real raster cells" if sample else "Train exact class means from real samples",
        "description": (
            "Top-level trusted extension with a canonical JSON string specification: "
            "version1 for sampleRegions, version2 for Image.sample, version1 for training. "
            "No URLs, callbacks or executable literal properties. Sampling uses real finite spatial "
            "cube cells and planar WGS84 Point/MultiPoint/Polygon/MultiPolygon regions; points select "
            "the containing half-open cell. Version1 polygons require positive intersection area; "
            "version2 polygons cover pixel centers and preserve band_order metadata. Version2 "
            "supports local deterministic factor/approximate numPixels selection before null filtering, "
            "optional retained null cells and finite missing tiles. Google RNG is not promised. "
            "Version1 NoData drops rows; overlapping different features preserve separate samples. "
            "At most1000 rows/50000 cells/1MB output, with existing grid/key/decoded-cell limits. "
            "Training accepts only a sample-table node, with existing exact minimumDistance metrics, "
            "explicit1..8 property schema, labels0..63, k1 CLASSIFICATION and shared work bounds. "
            "Complete runtime, spherical/global and Google equivalence are not established."),
        "categories": ["cubes", "vector-cubes"],
        "parameters": [
            {"name": "data", "description": "Spatial raster cube" if sample else "Actual bounded sample table",
             "schema": CUBE if sample else {"type": "object", "subtype": "vector-cube"}},
            {"name": "spec", "description": "Validated canonical JSON sampling/training specification",
             "schema": {"type": "string", "maxLength": 1_000_000}},
        ],
        "returns": {"description": "Actual bounded feature table" if sample else "Exact trained class-center model",
                    "schema": {"type": "object", "subtype": "vector-cube" if sample else "classifier-model"}},
    }
