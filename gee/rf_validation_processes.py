"""Typed process edges for runtime RF feature predictions and matrix values."""
from __future__ import annotations

from .rf_validation_spec import (
    decode_classify_spec, decode_feature_rows, decode_matrix_spec,
    decode_metric_spec,
)


CLASSIFY_ROWS = "local_ee_smile_rf_classify_rows"
CLASSIFY_SAMPLES = "local_ee_smile_rf_classify_samples"
RF_CONFUSION = "local_ee_smile_rf_confusion"
ERROR_MATRIX = "local_ee_error_matrix"
CONFUSION_VALUE = "local_ee_confusion_value"
CLASSIFIED_PRODUCERS = frozenset({CLASSIFY_ROWS, CLASSIFY_SAMPLES})
MATRIX_PRODUCERS = frozenset({RF_CONFUSION, ERROR_MATRIX})
SAMPLE_PRODUCERS = frozenset({"local_ee_sample_regions", "local_ee_sample_table_op"})
TRAINERS = frozenset({"local_ee_train_smile_rf_rows", "local_ee_train_smile_rf_samples"})
VALIDATION_PROCESSES = CLASSIFIED_PRODUCERS | MATRIX_PRODUCERS | {CONFUSION_VALUE}
JSON_PRODUCERS = CLASSIFIED_PRODUCERS | {CONFUSION_VALUE}
MODEL_CONSUMERS = CLASSIFIED_PRODUCERS | {RF_CONFUSION, "local_ee_smile_rf"}


def _source(value, nodes, producers):
    if (type(value) is not dict or set(value) != {"from_node"}
            or type(value["from_node"]) is not str
            or nodes.get(value["from_node"], {}).get("process_id") not in producers):
        raise ValueError("Runtime validation requires a direct audited producer reference")
    return nodes[value["from_node"]]


def validate_validation_process(name, arguments, depth, node_context):
    fields = {
        CLASSIFY_ROWS: {"rows", "spec", "model"},
        CLASSIFY_SAMPLES: {"data", "spec", "model"},
        RF_CONFUSION: {"model"}, ERROR_MATRIX: {"data", "spec"},
        CONFUSION_VALUE: {"data", "spec"},
    }[name]
    if depth != 0 or type(arguments) is not dict or set(arguments) != fields:
        raise ValueError("Runtime validation requires exact top-level process arguments")
    nodes = node_context if type(node_context) is dict else {}
    if name in CLASSIFIED_PRODUCERS | {RF_CONFUSION}:
        _source(arguments["model"], nodes, TRAINERS)
    if name in CLASSIFIED_PRODUCERS:
        spec = decode_classify_spec(arguments["spec"])
        if name == CLASSIFY_ROWS:
            from .table_values import columns

            data = decode_feature_rows(arguments["rows"])
            original = columns(data)
            # Canonical JSON sorts property keys; the explicit spec retains
            # the logical pre-serialization header order independently.
            expected = {*original, spec["output_name"]}
            if (spec["output_name"] in original or expected != set(spec["columns"])
                    or len(spec["columns"]) != len(original) + 1):
                raise ValueError("RF output columns differ from the original feature table")
        else:
            _source(arguments["data"], nodes, SAMPLE_PRODUCERS)
    elif name == ERROR_MATRIX:
        _source(arguments["data"], nodes, SAMPLE_PRODUCERS | CLASSIFIED_PRODUCERS)
        decode_matrix_spec(arguments["spec"])
    elif name == CONFUSION_VALUE:
        _source(arguments["data"], nodes, MATRIX_PRODUCERS)
        decode_metric_spec(arguments["spec"])


def validate_json_sink(arguments, nodes, depth):
    if depth != 0 or type(arguments) is not dict or set(arguments) != {"data", "format"}:
        raise ValueError("JSON output requires an exact top-level trusted runtime result sink")
    _source(arguments["data"], nodes, JSON_PRODUCERS)


def _columns(nodes, reference):
    from .sampling_graph import sample_chain
    from .sampling_spec import decode_sampling_spec
    from .sample_table_schema import sampled_columns

    node = nodes[reference]
    if node["process_id"] in CLASSIFIED_PRODUCERS:
        return decode_classify_spec(node["arguments"]["spec"])["columns"]
    origin, operations = sample_chain(nodes, reference)
    return sampled_columns(decode_sampling_spec(origin["arguments"]["spec"]), operations)


def _known_empty(nodes, reference):
    node = nodes[reference]
    return (node["process_id"] == CLASSIFY_ROWS
            and not decode_feature_rows(node["arguments"]["rows"])["features"])


def validate_validation_dependencies(nodes):
    from .smile_rf_processes import _scoped_references
    from .smile_rf_spec import decode_rf_spec

    for node in nodes.values():
        name, args = node["process_id"], node.get("arguments", {})
        if name in MATRIX_PRODUCERS and node.get("result"):
            raise ValueError("Opaque matrices require a bounded ConfusionMatrix accessor")
        if name == CLASSIFY_SAMPLES:
            original = _columns(nodes, args["data"]["from_node"])
            spec = decode_classify_spec(args["spec"])
            if (spec["output_name"] in original
                    or spec["columns"] != [*original[:-1], spec["output_name"], ".geo"]):
                raise ValueError("RF output columns differ from the original sampled table")
        if name in CLASSIFIED_PRODUCERS:
            model = nodes[args["model"]["from_node"]]
            schema = decode_rf_spec(model["arguments"]["spec"])["schema"]
            empty = name == CLASSIFY_ROWS and not decode_feature_rows(args["rows"])["features"]
            if not empty and not set(schema) <= set(decode_classify_spec(args["spec"])["columns"][:-2]):
                raise ValueError("RF feature query is missing trained schema columns")
        if name == ERROR_MATRIX:
            spec = decode_matrix_spec(args["spec"])
            available = set(_columns(nodes, args["data"]["from_node"])) - {"system:index", ".geo"}
            empty = _known_empty(nodes, args["data"]["from_node"])
            if empty and spec["order"] is None:
                raise ValueError("Empty error matrices require an explicit order")
            if not empty and not {spec["actual"], spec["predicted"]} <= available:
                raise ValueError("Error matrix fields must exist in the real table columns")
        for parameter, value in args.items():
            for reference, direct in _scoped_references(value):
                producer = nodes[reference]["process_id"]
                if producer in MATRIX_PRODUCERS:
                    if not (name == CONFUSION_VALUE and parameter == "data" and direct):
                        raise ValueError("Opaque matrices can only feed their direct accessor data parameter")
                elif producer in CLASSIFIED_PRODUCERS:
                    if not (direct and parameter == "data" and name in {ERROR_MATRIX, "save_result"}):
                        raise ValueError("Classified feature tables require a direct matrix or result consumer")
                    if name == "save_result" and str(args.get("format", "")).lower() not in {"csv", "json"}:
                        raise ValueError("Classified feature tables support CSV or JSON only")
                elif producer == CONFUSION_VALUE:
                    if not (direct and parameter == "data" and name == "save_result"
                            and str(args.get("format", "")).lower() == "json"):
                        raise ValueError("Runtime matrix values only support direct JSON output")


def validation_process_spec(name):
    schema = {"type": "object", "subtype": "vector-cube"}
    params = []
    if name != RF_CONFUSION:
        params.append({"name": "rows" if name == CLASSIFY_ROWS else "data",
                       "description": "Canonical bounded feature JSON" if name == CLASSIFY_ROWS else "Audited runtime producer",
                       "schema": {"type": "string", "maxLength": 1_000_000} if name == CLASSIFY_ROWS else schema})
        params.append({"name": "spec", "description": "Exact canonical version1 specification",
                       "schema": {"type": "string", "maxLength": 16_384}})
    if name in CLASSIFIED_PRODUCERS | {RF_CONFUSION}:
        params.append({"name": "model", "description": "Opaque actual Smile trainer result",
                       "schema": {"type": "object", "subtype": "classifier-model"}})
    return {"id": name, "experimental": True, "categories": ["machine-learning"],
            "summary": "Bounded runtime RF feature prediction and validation",
            "description": "Actual trusted model predictions and resubstitution counts; finite1000-row/64-class bounded tables. No compiler fitting, external URLs or model serialization. Metrics retain existing static numerical policies; Google parity is unverified.",
            "parameters": params,
            "returns": {"description": "Typed table, opaque matrix or bounded JSON value",
                        "schema": schema if name in CLASSIFIED_PRODUCERS else {"type": "object"}}}
