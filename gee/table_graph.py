"""Canonical, data-only table graphs for the existing isolated batch runner."""
from __future__ import annotations

import copy
import os
from pathlib import Path

from .artifacts import artifact_path, output_dir
from .table_values import render_csv
from .table_component_validation import EE_COMPONENTS


TABLE_PROCESS = "local_ee_table"


def has_table_node(graph):
    """Inspect nodes only; feature property names never become executable nodes."""
    return isinstance(graph, dict) and any(
        isinstance(node, dict) and node.get("process_id") == TABLE_PROCESS
        for node in graph.values()
    )


def table_input_graph(data, selected):
    """Return the typed input; make_job adds the ordinary save_result node."""
    render_csv(data, selected, geometry_profile=EE_COMPONENTS)
    return {"gee_table": {
        "process_id": TABLE_PROCESS,
        "arguments": {"data": copy.deepcopy(data), "columns": list(selected)},
        "result": True,
    }}


def validate_table_graph(graph):
    """Require precisely one literal input and one direct CSV sink.

    Do not apply the generic DAG visitor to the literal FeatureCollection:
    properties such as from_node/process_id/process_graph are ordinary data.
    The table-only shape prevents those values from entering other processes.
    """
    if not isinstance(graph, dict) or len(graph) != 2:
        raise ValueError("Inline table export requires exactly an input and CSV sink")
    loads, saves = [], []
    for key, node in graph.items():
        if (not isinstance(key, str) or not key or not isinstance(node, dict)
                or set(node) - {"process_id", "arguments", "result", "description"}
                or not isinstance(node.get("arguments"), dict)
                or ("description" in node and not isinstance(node["description"], str))
                or ("result" in node and type(node["result"]) is not bool)):
            raise ValueError("Invalid inline table node")
        if node.get("process_id") == TABLE_PROCESS:
            loads.append((key, node))
        elif node.get("process_id") == "save_result":
            saves.append((key, node))
        else:
            raise ValueError("Inline tables cannot be combined with raster processes")
    if len(loads) != 1 or len(saves) != 1:
        raise ValueError("Inline table export requires one input and one CSV sink")
    load_id, load = loads[0]
    _, save = saves[0]
    args = load["arguments"]
    sink = save["arguments"]
    if set(args) != {"data", "columns"}:
        raise ValueError("Inline table input requires literal data and columns")
    if (load.get("result", False) or save.get("result") is not True
            or set(sink) != {"data", "format"}
            or sink["data"] != {"from_node": load_id}
            or sink["format"] != "CSV"):
        raise ValueError("Inline table sink must directly save its input as CSV")
    render_csv(args["data"], args["columns"], geometry_profile=EE_COMPONENTS)
    return args["data"], args["columns"]


def execute_table_graph(graph, job):
    """Write a validated CSV in the batch child, before any JVM initialization.

    False delegates ordinary raster graphs to GeoTrellis. A malformed table
    graph raises rather than falling through to a different execution path.
    NativeClient still launches this entry point through its existing sandbox.
    """
    if not has_table_node(graph):
        return False
    data, selected = validate_table_graph(graph)
    text = render_csv(data, selected, geometry_profile=EE_COMPONENTS)
    job = Path(job).absolute()
    if job.parent.name != "jobs":
        raise ValueError("Inline table output must belong to its physical job")
    folder = output_dir(job.parent.parent, job.name)
    if folder.parent != job.resolve():
        raise ValueError("Inline table output must belong to its physical job")
    target = folder / "openEO.csv"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(text)
    artifact_path(job.parent.parent, job.name, target.name)
    return True


def table_process_spec():
    return {
        "id": TABLE_PROCESS,
        "summary": "Export bounded literal local features as CSV",
        "description": (
            "Data-only input for a two-node CSV export graph. No paths, URLs, callbacks "
            "or raster combinations. Individually valid planar MultiPolygon parts "
            "are preserved, including overlaps; no union or topology repair. "
            "Whole-table geometry preflight is bounded to 50000 work steps. "
            "Limits: 1000 rows, 256 columns, 50000 cells and "
            "1 MB UTF-8 input/output. Existing serialized EE expression/graph caps also "
            "apply; envelopes and Unicode escaping can reject smaller tables."),
        "experimental": True,
        "categories": ["vector-cubes"],
        "parameters": [
            {"name": "data", "description": "Literal finite GeoJSON FeatureCollection",
             "schema": {"type": "object", "subtype": "geojson"}},
            {"name": "columns", "description": "Unique output property names in order",
             "schema": {"type": "array", "items": {"type": "string"}}},
        ],
        "returns": {"description": "Bounded local feature table",
                    "schema": {"type": "object", "subtype": "vector-cube"}},
    }
