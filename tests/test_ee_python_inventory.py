"""The Python catalogue retains exact metadata without claiming backend support."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp("python-inventory")
    documents = []
    for name in ("first.json", "second.json"):
        output = folder / name
        subprocess.run(
            [sys.executable, "-m", "scripts.ee_python_inventory", "--output", str(output)],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=30,
        )
        documents.append(output.read_text(encoding="utf-8"))
    return documents


def _callables(report):
    rows = list(report["unbound_algorithm_callables"])
    for surface in report["python_surfaces"]:
        rows.extend(surface["functions"])
        for cls in surface["classes"]:
            rows.extend([cls["constructor"], *cls["methods"]])
    return {row["path"]: row for row in rows}


def test_every_pinned_signature_and_argument_is_retained(generated):
    report = json.loads(generated[0])
    pinned = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())["algorithms"]
    expected = sorted(pinned, key=lambda item: item["name"].removeprefix("algorithms/"))
    assert len(report["algorithms"]) == report["summary"]["algorithm_signature_count"] == 991
    assert [row["official_signature"] for row in report["algorithms"]] == expected
    assert report["summary"]["algorithm_argument_count"] == sum(len(row.get("arguments", [])) for row in pinned)
    assert report["network_evidence"]["attempt_count"] == 0
    assert report["network_evidence"]["attempts_by_operation"] == {}
    assert "socket.socket.connect" in report["network_evidence"]["instrumented_operations"]
    for row in report["algorithms"]:
        assert row["evidence"]["serialization"] == "not_exhaustively_probed"
        assert row["evidence"]["compilation"] == "not_verified_per_signature"
        assert row["evidence"]["engine_execution"] == "not_verified_per_signature"
        assert row["evidence"]["independent_numerical_validation"] == "not_verified_per_signature"
        assert row["evidence"]["google_same_data_comparison"] == "not_run"


def test_python_bindings_and_actual_parameters_are_distinct_from_algorithm_args(generated):
    report = json.loads(generated[0])
    by_name = {row["name"]: row for row in report["algorithms"]}
    callables = _callables(report)
    assert "ee.Image.add" in by_name["Image.add"]["python_bindings"]
    assert "ee.Array.matrixMultiply" in by_name["Array.matrixMultiply"]["python_bindings"]
    assert "ee.ImageCollection.aggregate_array" in by_name["AggregateFeatureCollection.array"]["python_bindings"]
    assert "ee.Algorithms.If" in by_name["If"]["python_bindings"]
    assert "ee.Filter.notNull" in by_name["Filter.notNull"]["python_bindings"]
    assert "ee.String.cat" in by_name["String.cat"]["python_bindings"]
    assert callables["ee.Image.select"]["deprecated_keyword_aliases"] == {
        "opt_names": "names", "opt_selectors": "selectors",
    }
    sequence = callables["ee.List.sequence"]["python_signature"]["parameters"]
    assert [parameter["name"] for parameter in sequence] == ["start", "end", "step", "count"]
    assert sequence[0]["required"] is True
    assert sequence[2]["default"] is None
    official = by_name["List.sequence"]["official_signature"]["arguments"]
    assert official[2]["defaultValue"] == 1.0
    assert "ee.batch.Export.image.toDrive" in callables
    assert "ee.data.computeValue" in callables
    assert "ee.oauth.authenticate" in callables
    assert "ee.ImageCollection.first" in by_name["Collection.first"]["python_bindings"]
    unmapped = [row["name"] for row in report["algorithms"] if not row["python_bindings"]]
    assert report["summary"]["unmapped_named_algorithms"] == unmapped
    assert report["summary"]["named_binding_algorithm_count"] + len(unmapped) == 991


def test_generation_is_deterministic_and_contains_no_machine_paths(generated):
    assert generated[0] == generated[1]
    assert generated[0] == (ROOT / "reports/gee-python-api-inventory.json").read_text(encoding="utf-8")
    for forbidden in ("/workspace/", "/home/", "/Users/", "0x7f", "Authorization:"):
        assert forbidden not in generated[0]
    assert "compatibility percentage" in json.loads(generated[0])["scope"]["compatibility"]


def test_configured_runtime_is_rejected_without_mutating_the_session():
    # Own the adapter's process just like production probe generation. Importing
    # it here would replace the legitimate EE session used by other test modules.
    code = textwrap.dedent("""
        import socket
        import ee
        from scripts.ee_python_api.inventory import build_inventory
        from scripts.ee_python_probes import generate_fixture

        generate_fixture()
        runtime = ee._local_ee_runtime
        initialize = ee.Initialize
        compute = ee.data.computeValue
        algorithms = ee.data.getAlgorithms
        local_map = ee.Map
        connect = socket.create_connection
        expression = ee.Number(7).add(3)
        before = ee.serializer.encode(expression, for_cloud_api=False)
        try:
            build_inventory()
        except RuntimeError as error:
            assert 'pristine SDK process' in str(error)
            assert 'separate process' in str(error)
        else:
            raise AssertionError('Adapted SDK silently produced an incomplete inventory')
        assert ee._local_ee_runtime is runtime
        assert ee.Initialize is initialize
        assert ee.data.computeValue is compute
        assert ee.data.getAlgorithms is algorithms
        assert ee.Map is local_map
        assert socket.create_connection is connect
        assert ee.serializer.encode(expression, for_cloud_api=False) == before
        assert len(ee.data.getAlgorithms()) == 991
    """)
    subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=30,
    )
