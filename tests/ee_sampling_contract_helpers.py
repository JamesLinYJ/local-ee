"""Shared small fixtures for the local sampling contract tests."""
from __future__ import annotations

import copy
import csv
import io
import json
from pathlib import Path

from gee.sampling_spec import encode_spec, prepare_sampling_spec

POINT = {"type": "Point", "coordinates": [0.5, 0.5]}
_DEFAULT_GEOMETRY = object()


def _feature(properties=None, geometry=_DEFAULT_GEOMETRY, identifier="region-0"):
    return {
        "type": "Feature",
        "id": identifier,
        "geometry": copy.deepcopy(POINT if geometry is _DEFAULT_GEOMETRY else geometry),
        "properties": {} if properties is None else copy.deepcopy(properties),
    }


def _collection(features=None):
    return {
        "type": "FeatureCollection",
        "features": [_feature({"label": 1})] if features is None else features,
    }


def _sample_text(*, bands=("red",), properties=None, geometries=False,
                 grid=None, features=None):
    return prepare_sampling_spec(
        _collection(features), list(bands), properties=properties,
        geometries=geometries, grid=grid,
    )


def _sample_object(**kwargs):
    return json.loads(_sample_text(**kwargs))


def _encode_sample_object(spec):
    return encode_spec(spec)


def _row(*, feature=0, row=0, col=0, x=0.5, y=0.5, values=None):
    return {
        "feature": feature,
        "row": row,
        "col": col,
        "x": x,
        "y": y,
        "values": [1.25] if values is None else values,
    }


def _write_csv(path: Path, text: str) -> Path:
    path.write_bytes(text.encode("utf-8"))
    return path


def _read_csv_rows(text):
    return list(csv.reader(io.StringIO(text, newline=""), strict=True))


def _rewrite_csv(text, change):
    rows = _read_csv_rows(text)
    change(rows)
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerows(rows)
    return output.getvalue()


def _valid_sampling_graph():
    source_properties = {
        "from_node": "this-is-data",
        "payload": {"process_id": "also-data", "from_node": "missing-node"},
    }
    sample = _sample_text(
        bands=["process_id"],
        properties=["from_node", "payload"],
        features=[_feature(source_properties)],
    )
    training = encode_spec({
        "version": 1,
        "metric": "manhattan",
        "class_property": "from_node",
        "schema": ["process_id"],
    })
    return {
        "source": {"process_id": "load_collection", "arguments": {"id": "synthetic"}},
        "samples": {
            "process_id": "local_ee_sample_regions",
            "arguments": {"data": {"from_node": "source"}, "spec": sample},
        },
        "model": {
            "process_id": "local_ee_train_minimum_distance",
            "arguments": {"data": {"from_node": "samples"}, "spec": training},
        },
        "classify": {
            "process_id": "local_ee_minimum_distance",
            "arguments": {
                "data": {"from_node": "source"},
                "model": {"from_node": "model"},
            },
            "result": True,
        },
    }
