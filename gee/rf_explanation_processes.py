"""Exact process contract for a trusted Smile model explanation projection."""
from __future__ import annotations

from .smile_rf_spec import decode_rf_spec


RF_EXPLAIN = "local_ee_smile_rf_explain"
MAX_EXPLANATION_SPEC_BYTES = 16_384
MAX_EXPLANATION_GRAPH_WORK = 150_000
MAX_EXPLANATION_GRAPH_WIRE_BYTES = 3_000_000
_SPEC_PREFLIGHT_WORK = 1
_SPEC_DECODE_WORK = 2
_SPEC_PREFLIGHT_WIRE_SCANS = 1
_SPEC_DECODE_WIRE_SCANS = 3


def preflight_explanation_graph(nodes):
    """Reserve aggregate graph-validation work before any RF spec is decoded.

    An explanation node decodes both its projection and its trainer spec. The
    trainer node itself is decoded once as well, so charge that base parse once
    per directly referenced trainer and each consumer parse per explanation.
    Only the RF explanation surface is metered here; ordinary RF graph behavior
    retains its existing validation path.
    """
    if type(nodes) is not dict:
        return
    from .rf_explanation_spec import _utf8_size

    work, wire = 0, 0
    seen_trainers = set()

    def scan_spec(text, work_per_byte, wire_per_byte):
        nonlocal work, wire
        work_allowance = (MAX_EXPLANATION_GRAPH_WORK - work) // work_per_byte
        wire_allowance = (MAX_EXPLANATION_GRAPH_WIRE_BYTES - wire) // wire_per_byte
        allowance = min(MAX_EXPLANATION_SPEC_BYTES, work_allowance, wire_allowance)
        if allowance <= 0:
            if work_allowance <= wire_allowance:
                raise ValueError("RF explanation graph exceeds the 150000-step object-work budget")
            raise ValueError("RF explanation graph exceeds the 3000000-byte wire-scan budget")
        try:
            size = _utf8_size(text, allowance)
        except ValueError as exc:
            if "valid UTF-8" in str(exc) or allowance == MAX_EXPLANATION_SPEC_BYTES:
                raise
            if work_allowance <= wire_allowance:
                raise ValueError("RF explanation graph exceeds the 150000-step object-work budget") from exc
            raise ValueError("RF explanation graph exceeds the 3000000-byte wire-scan budget") from exc
        work += size * work_per_byte
        wire += size * wire_per_byte
        return size

    for node in nodes.values():
        if type(node) is not dict or node.get("process_id") != RF_EXPLAIN:
            continue
        if (set(node) - {"process_id", "arguments", "result", "description", "namespace"}
                or node.get("namespace")
                or ("description" in node and type(node["description"]) is not str)
                or ("result" in node and type(node["result"]) is not bool)):
            continue
        arguments = node.get("arguments")
        if type(arguments) is not dict or set(arguments) != {"model", "spec"}:
            continue
        reference = arguments.get("model")
        if (type(reference) is not dict or set(reference) != {"from_node"}
                or type(reference.get("from_node")) is not str):
            continue
        trainer_key = reference["from_node"]
        source = nodes.get(trainer_key)
        if (type(source) is not dict or source.get("process_id") not in {
            "local_ee_train_smile_rf_rows", "local_ee_train_smile_rf_samples",
        }):
            continue
        source_arguments = source.get("arguments")
        trainer_text = (source_arguments.get("spec")
                        if type(source_arguments) is dict else None)
        if type(trainer_text) is str:
            new_trainer = trainer_key not in seen_trainers
            trainer_work = _SPEC_PREFLIGHT_WORK + _SPEC_DECODE_WORK
            trainer_wire = _SPEC_PREFLIGHT_WIRE_SCANS + _SPEC_DECODE_WIRE_SCANS
            if new_trainer:
                trainer_work += _SPEC_DECODE_WORK
                trainer_wire += _SPEC_DECODE_WIRE_SCANS
            scan_spec(trainer_text, trainer_work, trainer_wire)
            seen_trainers.add(trainer_key)
        projection_text = arguments.get("spec")
        if type(projection_text) is str:
            scan_spec(
                projection_text,
                _SPEC_PREFLIGHT_WORK + _SPEC_DECODE_WORK,
                _SPEC_PREFLIGHT_WIRE_SCANS + _SPEC_DECODE_WIRE_SCANS,
            )

    if work > MAX_EXPLANATION_GRAPH_WORK:
        raise ValueError("RF explanation graph exceeds the 150000-step object-work budget")
    if wire > MAX_EXPLANATION_GRAPH_WIRE_BYTES:
        raise ValueError("RF explanation graph exceeds the 3000000-byte wire-scan budget")


def validate_explanation_process(arguments, depth, nodes):
    from .rf_explanation_spec import decode_explanation_spec

    if depth != 0 or type(arguments) is not dict or set(arguments) != {"model", "spec"}:
        raise ValueError("RF explanation requires exact top-level model/spec arguments")
    reference = arguments["model"]
    if (type(reference) is not dict or set(reference) != {"from_node"}
            or type(reference["from_node"]) is not str or type(nodes) is not dict):
        raise ValueError("RF explanation requires a direct audited trainer reference")
    source = nodes.get(reference["from_node"], {})
    if source.get("process_id") not in {
        "local_ee_train_smile_rf_rows", "local_ee_train_smile_rf_samples",
    }:
        raise ValueError("RF explanation requires a direct audited trainer reference")
    model = decode_rf_spec(source["arguments"]["spec"])
    query = decode_explanation_spec(arguments["spec"])
    if query["schema"] != model["schema"] or query["trees"] != model["number_of_trees"]:
        raise ValueError("RF explanation schema/tree count differs from its real trainer")


def explanation_process_spec():
    return {
        "id": RF_EXPLAIN, "experimental": True, "categories": ["machine-learning"],
        "summary": "Read actual bounded Smile model importance and diagnostics",
        "description": "Actual trained model only; three numeric diagnostic fields and bounded projections. Raw Smile1.5.3 OOB error policy, no Google parity, arbitrary model bytes or external requests. JSON only.",
        "parameters": [
            {"name": "model", "description": "Direct audited actual Smile trainer result",
             "schema": {"type": "object", "subtype": "classifier-model"}},
            {"name": "spec", "description": "Exact canonical version1 projection specification",
             "schema": {"type": "string", "maxLength": 16_384}},
        ],
        "returns": {"description": "Owned bounded diagnostic JSON projection", "schema": {}},
    }
