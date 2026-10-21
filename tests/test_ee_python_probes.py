"""Offline instrumentation must fail when the SDK or a probe tries networking."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from gee.ee_python_transport import LocalEETransport
from scripts.ee_python_api.offline import OfflineGuard, OfflineViolation


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("operation", ["create_connection", "getaddrinfo", "connect", "sendto", "local_transport"])
def test_guard_denies_and_counts_network_entry_points(operation):
    with pytest.raises(OfflineViolation, match="Offline generator attempted"):
        with OfflineGuard() as guard:
            if operation == "create_connection":
                socket.create_connection(("127.0.0.1", 9))
            elif operation == "getaddrinfo":
                socket.getaddrinfo("invalid.example", 443)
            elif operation == "local_transport":
                LocalEETransport("http://127.0.0.1:8787/openeo/1.2", "a" * 48).request({"action": "evaluate"})
            else:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    if operation == "connect":
                        sock.connect(("127.0.0.1", 9))
                    else:
                        sock.sendto(b"denied", ("127.0.0.1", 9))
    assert guard.evidence()["attempt_count"] == 1


def test_guard_detects_swallowed_attempts_and_restores_functions():
    original = socket.create_connection
    with pytest.raises(OfflineViolation, match="swallowed"):
        with OfflineGuard() as guard:
            try:
                socket.create_connection(("127.0.0.1", 9))
            except OfflineViolation:
                pass
    assert guard.evidence()["attempt_count"] == 1
    assert socket.create_connection is original


def test_probes_serialize_deterministically_and_distinguish_unrun_stages(tmp_path):
    output = tmp_path / "probes.json"
    command = [sys.executable, "-m", "scripts.ee_python_probes", "--output", str(output)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([*command, "--check"], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
    report = json.loads(output.read_text())
    assert report == json.loads((ROOT / "tests/fixtures/ee-python-1.7.49.json").read_text())
    assert len(report["cases"]) == 50
    assert len({row["id"] for row in report["cases"]}) == 50
    assert report["network_requests"] == report["network_evidence"]["attempt_count"] == 0
    assert all(row["serialization"]["status"] == "passed" for row in report["cases"])
    for row in report["cases"]:
        for stage in ("engine_execution", "independent_numerical_validation", "google_same_data_comparison"):
            assert row[stage]["status"] == "not_run"
    # Check mode must preserve an intentionally changed fixture and report drift.
    output.write_text("{}\n")
    result = subprocess.run([*command, "--check"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert output.read_text() == "{}\n"
