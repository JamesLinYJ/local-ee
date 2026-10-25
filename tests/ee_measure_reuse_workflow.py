"""Run exact full table requests through trusted dispatch and physical CSV."""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path

from table_export_support import USER, run_batch


SUPPLEMENTAL_CONFIG = {
    "description": "Wave73 supplemental centroid ownership",
    "csv_selectors": ["system:index", "source_id", "label", "nested", "geometry_center", ".geo"],
}


def supplemental_ownership_collection(ee, geometry):
    """Additional ownership control, never a substitute for the full formulas."""
    features = [ee.Feature({
        "type": "Feature", "id": f"wave73-owner-{name}", "geometry": geometry,
        "properties": {"label": name, "nested": {"owner": [name], "numbers": [rank, rank + 1]}},
    }) for rank, name in enumerate(("left", "right"))]
    projection = ee.Projection("EPSG:4326")

    def attach_centers(feature):
        return feature.centroid(proj=projection).set({
            "source_id": feature.id(),
            "geometry_center": feature.geometry().centroid(proj=projection).coordinates(),
        })

    return ee.FeatureCollection(features).map(attach_centers)


def export_original(integration, collection, record):
    config = record["config"]
    task = integration.ee.batch.Export.table.toDrive(
        collection=collection, description=config["description"],
        fileFormat="CSV", selectors=config["csv_selectors"],
    )
    task.start()
    export_request = next(request for request in integration.requests
                          if request["action"] == "export_table")
    assert export_request["expression"] == record["wire"]
    assert export_request["options"]["selectors"] == config["csv_selectors"]
    return finish_and_read(integration, task.id, config)


def finish_and_read(integration, job_id, config):
    result = run_batch(integration, job_id)
    assert result.row["status"] == "finished", result.row
    from gee.backend import Jobs

    assets = Jobs().get_result_assets(job_id, USER)
    filename = config["description"] + ".csv"
    assert set(assets) == {filename}
    path = result.job_dir / "out" / filename
    assert Path(assets[filename]["href"]) == path
    raw = path.read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    return rows, {
        "job_id": job_id, "worker_status": result.row["status"],
        "physical_csv_sha256": hashlib.sha256(raw).hexdigest(),
        "physical_csv_bytes": len(raw), "physical_csv_text": raw.decode(),
        "asset_path": str(path), "rows": rows,
        "process": result.row["process"],
        "dispatch_actions": [request["action"] for request in integration.requests],
        "scope": "Actual local dispatch, worker prepare/finish, pure table engine and "
                 "physical CSV. In-memory database/queue and substituted NativeTask "
                 "launcher; no HTTP, live service, native supervisor, Spark or Google.",
    }
