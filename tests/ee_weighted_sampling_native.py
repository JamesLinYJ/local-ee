"""Native probe fixture for Wave65, conditional only on the ignored audit manifest."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

import pytest

from ee_weighted_sampling_helpers import ROOT
from scripts.probe_weighted_sampling_native import EXPECTED_MANIFEST, run_probe


def native_probe_or_skip(manifest_path: Path | None = None,
                         receipt_dir: Path | None = None,
                         probe_runner=None) -> dict:
    """Skip native acceptance only when the designated manifest path is absent."""
    manifest_path = Path(EXPECTED_MANIFEST if manifest_path is None else manifest_path)
    if not os.path.lexists(manifest_path):
        receipt_dir = Path(receipt_dir or ROOT / "audit/gee-python-wave65/workflow")
        receipt_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        receipt = receipt_dir / (
            f"native-prerequisite-missing-{stamp}-{os.getpid()}-{uuid.uuid4().hex[:12]}.json"
        )
        payload = {
            "format": "local-ee-weighted-sampling-prerequisite-v1",
            "status": "skipped",
            "reason": "designated current audit manifest is absent",
            "missing_prerequisite": str(manifest_path.resolve()),
            "skipped_scope": [
                "native mask apply through existing Image.sample/sampleRegions tile kernels",
                "official SDK getInfo through native sampled rows, CSV dispatch/worker/file/readback",
            ],
            "still_runnable_scope": [
                "offline official Python/JavaScript SDK wire parity",
                "compiler graphs through sample operations and training descriptors",
            ],
            "google_requests": 0,
            "spark_context_started": False,
            "deployment_eligible": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        descriptor = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        pytest.skip(
            "native weighted-sampling acceptance skipped: designated current audit manifest "
            f"is absent at {manifest_path}"
        )

    runner = run_probe if probe_runner is None else probe_runner
    return runner(manifest_path=manifest_path, receipt_dir=receipt_dir)


@pytest.fixture(scope="module")
def native_probe():
    """Compile one temporary Scala harness against the strictly verified JAR."""
    return native_probe_or_skip(
        receipt_dir=ROOT / "audit/gee-python-wave65/workflow",
    )
