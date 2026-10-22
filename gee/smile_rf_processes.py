"""Strict producer types and process specifications for runtime Smile models."""
from __future__ import annotations

from .smile_rf_spec import decode_rf_rows, decode_rf_spec


RF_ROWS = "local_ee_train_smile_rf_rows"
RF_SAMPLES = "local_ee_train_smile_rf_samples"
RF_CLASSIFY = "local_ee_smile_rf"
RF_TRAINERS = frozenset({RF_ROWS, RF_SAMPLES})
RF_PROCESSES = RF_TRAINERS | {RF_CLASSIFY}
# Explicit raster return types from the pinned local process specifications.
# Scalar/vector/any-return processes do not become cubes through a node ref.
RF_RASTER_PRODUCERS = frozenset({
    "load_collection", "filter_bbox", "filter_temporal", "filter_bands", "mask",
    "ndvi", "reduce_dimension", "aggregate_temporal_period", "resample_spatial",
    "apply", "apply_dimension", "rename_labels", "merge_cubes", "mask_polygon",
    "add_dimension", "drop_dimension", "local_ee_to_double", "local_ee_to_float",
    "local_ee_constant_on_grid", "local_ee_unmask", "local_ee_drop_single_time",
    "local_ee_reduce_bands", "local_ee_minimum_distance", "local_ee_remap", RF_CLASSIFY,
})


def _reference(value):
    if (type(value) is not dict or set(value) != {"from_node"}
            or type(value["from_node"]) is not str or not value["from_node"]):
        raise ValueError("Random forest processes require canonical top-level node references")
    return value["from_node"]


def validate_rf_process(name, arguments, depth, node_context):
    required = {"rows", "spec"} if name == RF_ROWS else {"data", "spec"}
    if name == RF_CLASSIFY:
        required = {"data", "model"}
    if depth != 0 or type(arguments) is not dict or set(arguments) != required:
        raise ValueError("Random forest processes require exact top-level arguments")
    if name in RF_TRAINERS:
        spec = decode_rf_spec(arguments["spec"])
        if name == RF_ROWS:
            decode_rf_rows(arguments["rows"], spec)
        else:
            _reference(arguments["data"])
        return
    data_key = _reference(arguments["data"])
    model_key = _reference(arguments["model"])
    nodes = node_context if type(node_context) is dict else {}
    if nodes.get(model_key, {}).get("process_id") not in RF_TRAINERS:
        raise ValueError("Random forest models must come from an audited Smile training producer")
    if nodes.get(data_key, {}).get("process_id") not in RF_RASTER_PRODUCERS:
        raise ValueError("Random forest prediction requires an audited raster cube producer")


def validate_rf_dependencies(nodes):
    """Sample chains retain schema; trusted RF models never cross algorithm types."""
    from .sampling_graph import _sampling_origin
    from .sampling_spec import decode_sampling_spec, sampling_columns
    from .rf_validation_processes import MODEL_CONSUMERS

    for node in nodes.values():
        name, arguments = node["process_id"], node.get("arguments", {})
        if name in RF_TRAINERS and node.get("result"):
            raise ValueError("Opaque random forest models can only feed audited prediction or evaluation")
        if name == RF_SAMPLES:
            source = _sampling_origin(nodes, arguments["data"]["from_node"])
            sample = decode_sampling_spec(source["arguments"]["spec"])
            spec = decode_rf_spec(arguments["spec"])
            columns = set(sampling_columns(sample)) - {"system:index", ".geo"}
            if not {spec["class_property"], *spec["schema"]} <= columns:
                raise ValueError("Random forest training fields must exist in sample-table columns")
        # Model objects have exactly one consumer contract. In particular they
        # cannot reach generic arithmetic, tables or a SaveResult serializer.
        for parameter, value in arguments.items():
            direct_model = name in MODEL_CONSUMERS and parameter == "model"
            for reference, direct in _scoped_references(value):
                if nodes[reference]["process_id"] in RF_TRAINERS:
                    if not direct_model or not direct:
                        raise ValueError("An opaque random forest model can only feed the prediction model parameter")


def _scoped_references(value, direct=True):
    """Follow this DAG's refs; strings are data, callbacks own separate DAGs.

    The ordinary graph validator already bounds nesting and verifies reference
    shapes, ownership and existence before the typed producer check runs.
    """
    if type(value) is dict:
        if set(value) == {"process_graph"}:
            return
        if set(value) == {"from_node"}:
            yield value["from_node"], direct
            return
        for child in value.values():
            yield from _scoped_references(child, False)
    elif type(value) is list:
        for child in value:
            yield from _scoped_references(child, False)


def rf_process_spec(name):
    raster = {"type": "object", "subtype": "raster-cube"}
    model = {"type": "object", "subtype": "classifier-model"}
    if name == RF_CLASSIFY:
        parameters = [
            {"name": "data", "description": "Schema-ordered finite raster cube", "schema": raster},
            {"name": "model", "description": "Opaque model from a trusted Smile trainer", "schema": model},
        ]
    else:
        literal = name == RF_ROWS
        parameters = [
            {"name": "rows" if literal else "data",
             "description": "Canonical version1 numeric training rows" if literal else "Audited sampled table",
             "schema": {"type": "string", "maxLength": 1_000_000} if literal else
                       {"type": "object", "subtype": "vector-cube"}},
            {"name": "spec", "description": "Canonical version1 Smile1.5.3 parameters and schema",
             "schema": {"type": "string", "maxLength": 16_384}},
        ]
    return {
        "id": name, "experimental": True, "categories": ["machine-learning"],
        "summary": "Predict with a trusted Smile random forest" if name == RF_CLASSIFY else "Train a bounded Smile random forest",
        "description": (
            "Pinned Smile1.5.3, CLASSIFICATION only; numeric1..8 input properties,2..1000 rows, "
            "2..64 contiguous labels from0,1..256 trees. All six constructor parameters are "
            "explicitly preserved. Training is serial and seeded on the calling JVM thread; "
            "no user Java serialization, URLs, model paths or runtime dependency downloads. "
            "RF150000 object/copy work including prior table operations capped at50000,3MB wire scan, "
            "single JSON1MB and1000000000 tree-row-feature-leaf work "
            "bound apply. Prediction preserves actual input precision, masks, grid and time. "
            "Google's Smile version, random sampling and numerical equivalence are unverified."
        ),
        "parameters": parameters,
        "returns": {"description": "Singleton classification band v" if name == RF_CLASSIFY else "Opaque trusted classifier",
                    "schema": raster if name == RF_CLASSIFY else model},
    }
