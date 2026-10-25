"""Physical CSV execution of the separately named two-row Wave72 formula."""
from __future__ import annotations

import csv
import hashlib
import io
import json

from table_export_support import USER, run_batch


def export_and_read(integration, collection, config):
    """Use real EE dispatch, worker preparation, table writer and asset readback.

    The shared test harness substitutes in-memory queue/database and launcher;
    no native service, HTTP, Spark or deployed runtime is involved.
    """
    task = integration.ee.batch.Export.table.toDrive(
        collection=collection, description=config["description"],
        fileFormat="CSV", selectors=config["selectors"],
    )
    task.start()
    result = run_batch(integration, task.id)
    assert result.row["status"] == "finished", result.row
    from gee.backend import Jobs

    assets = Jobs().get_result_assets(task.id, USER)
    filename = config["description"] + ".csv"
    assert set(assets) == {filename}
    path = result.job_dir / "out" / filename
    assert assets[filename]["href"] == str(path)
    raw = path.read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    return rows, {
        "task_id": task.id, "worker_status": result.row["status"],
        "physical_csv_sha256": hashlib.sha256(raw).hexdigest(),
        "physical_csv_bytes": len(raw), "physical_csv_text": raw.decode(),
        "asset_path": str(path), "rows": rows,
        "process": json.loads(json.dumps(result.row["process"])),
        "dispatch_actions": [request["action"] for request in integration.requests],
        "limits": "Synthetic database/queue and substituted launcher; actual local dispatch, "
                  "worker prepare/finish, pure table engine and physical CSV asset readback. "
                  "No HTTP/native-service/Spark/Google/private-data acceptance.",
    }
