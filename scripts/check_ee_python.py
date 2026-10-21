"""Official Python SDK -> local HTTP -> Seatbelt -> GeoTrellis acceptance.

Requires a NEW GEE_AUDIT_DIR and running native services. Uses existing local
research data without modifying the catalogue or accounts. Keeps test jobs and
downloaded evidence, never prints credentials or tokens.
"""
import hashlib
import csv
import io
import json
import os
from pathlib import Path
import time

import numpy as np
from rasterio.io import MemoryFile
import requests


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://localhost:8787"
CODE = '''import ee, json, time, os, socket, uuid
from concurrent.futures import ThreadPoolExecutor
ee.Initialize()
ee.Initialize()
assert ee.__version__ == "1.7.49"
assert ee.Number(2).add(3).getInfo() == 5
assert ee.Date("2024-01-01").millis().getInfo() == 1704067200000
assert "OPENEO_TOKEN" not in os.environ
for method in [ee.Authenticate, lambda: ee.Initialize(project="cloud-project")]:
    try:
        method()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Cloud initialization unexpectedly accepted")
try:
    socket.create_connection(("198.51.100.1", 443), timeout=1)
except PermissionError:
    pass
else:
    raise AssertionError("Public networking unexpectedly allowed")
collection = ee.ImageCollection("sentinel-2-l2a")
assert collection.size().getInfo() > 0
source = ee.Image(collection.first())
ndvi = source.normalizedDifference(["nir", "red"]).rename("NDVI")
assert ndvi.bandNames().getInfo() == ["NDVI"]
assert ndvi.getInfo()["bands"][0]["id"] == "NDVI"
roi = source.geometry()
send = ee._local_ee_runtime["transport"].request
payload = {"action": "export_image", "request_id": str(uuid.uuid4()),
    "expression": ee.serializer.encode(ndvi, for_cloud_api=False),
    "options": {"description": "python-sdk-retry", "scale": 10}}
with ThreadPoolExecutor(max_workers=4) as pool:
    duplicates = list(pool.map(lambda _: send(payload)["job_id"], range(4)))
assert len(set(duplicates)) == 1, duplicates
assert send(payload)["job_id"] == duplicates[0]
try:
    send({**payload, "options": {**payload["options"], "description": "changed"}})
except RuntimeError:
    pass
else:
    raise AssertionError("Conflicting SDK request ID was accepted")
send({"action": "cancel", "job_id": duplicates[0]})
Map.clear()
Map.centerObject(roi, 13)
Map.setZoom(12)
layer = Map.addLayer(ndvi, {"min": -1, "max": 1}, "Python SDK NDVI")
cancelled = ee.batch.Export.image.toDrive(ndvi, "python-sdk-cancel", region=roi, scale=10)
cancelled.start()
cancelled.cancel()
assert cancelled.status()["state"] == "CANCELLED"
task = ee.batch.Export.image.toDrive(
    ndvi, "python-sdk-export", region=roi, scale=10, crs="EPSG:32649",
    fileNamePrefix="python-sdk-ndvi", maxPixels=1e8)
task.start()
assert any(item.id == task.id for item in ee.batch.Task.list())
deadline = time.monotonic() + 95
while task.active() and time.monotonic() < deadline:
    time.sleep(.5)
status = task.status()
assert status["state"] == "COMPLETED", status
print("LOCAL_EE_PYTHON_OK " + json.dumps({
    "sdk": ee.__version__, "export_id": task.id, "map_id": layer["job_id"],
    "cancel_id": cancelled.id, "task_state": status["state"],
    "scalar": 5, "date_millis": 1704067200000, "concurrent_retries": 4,
    "collection_size": collection.size().getInfo()}))
'''
TABLE_CODE = '''import ee, json, time
ee.Initialize()
source = ee.Image(ee.ImageCollection("sentinel-2-l2a").first())
ndvi = source.normalizedDifference(["nir", "red"]).rename("NDVI")
stats = ndvi.reduceRegion(ee.Reducer.mean(), source.geometry(), 10, "EPSG:32649")
value = stats.getInfo()
table = ee.FeatureCollection([ee.Feature(None, stats)])
task = ee.batch.Export.table.toDrive(table, "python-sdk-table", fileFormat="CSV", selectors=["NDVI"])
task.start()
deadline = time.monotonic() + 80
while task.active() and time.monotonic() < deadline:
    time.sleep(.5)
assert task.status()["state"] == "COMPLETED", task.status()
print("LOCAL_EE_PYTHON_TABLE_OK " + json.dumps({"export_id": task.id, "value": value}))
'''


def run():
    audit = Path(os.environ["GEE_AUDIT_DIR"]).resolve()
    audit.mkdir(parents=True, exist_ok=False)
    login = dict(line.split(": ", 1) for line in (ROOT / "deploy/native-login.txt").read_text().splitlines())
    session = requests.Session()
    session.trust_env = False
    session.headers["Origin"] = BASE

    def request(path, method="get", **kwargs):
        response = getattr(session, method)(BASE + path, timeout=20, **kwargs)
        response.raise_for_status()
        return response

    request("/workbench/login", "post", json={"username": login["Username"], "password": login["Password"]})
    del login
    def execute(code, name, marker):
        parent = request("/workbench/jobs", "post", json={
            "title": "验收 · 官方 Python EE · " + name, "language": "python", "code": code}).json()["id"]
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            row = request(f"/workbench/jobs/{parent}/logs").json()
            if row["status"] in {"finished", "error", "canceled"}:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Python SDK parent did not terminate within 150 seconds")
        (audit / (name + "-parent.json")).write_text(json.dumps(row, indent=2, ensure_ascii=False))
        if row["status"] != "finished":
            raise RuntimeError("Python SDK acceptance failed; see retained local parent evidence")
        line = next(line for line in row["logs"].splitlines() if line.startswith(marker + " "))
        return parent, json.loads(line.split(" ", 1)[1])

    parent, proof = execute(CODE, "raster", "LOCAL_EE_PYTHON_OK")
    export_id = proof["export_id"]
    jobs = request("/workbench/jobs").json()
    output = next(job for job in jobs if job["id"] == export_id)
    assert output["language"] == "python" and output["context"]["source_job_id"] == parent
    assert output["status"] == "finished"
    filename = next(name for name in output["assets"] if name.endswith(".tif"))
    content = request(f"/workbench/jobs/{export_id}/files/{filename}").content
    (audit / "python-sdk-ndvi.tif").write_bytes(content)
    with MemoryFile(content) as memory, memory.open() as raster:
        values = raster.read(1, masked=True).compressed()
        assert raster.count == 1 and len(values) > 0
        assert np.isfinite(values).all() and np.all((values >= -1) & (values <= 1))
        assert raster.crs.to_epsg() == 32649 and tuple(raster.res) == (10, 10)
        proof["raster"] = {"bands": raster.count, "crs": str(raster.crs),
            "resolution": list(raster.res), "valid_pixels": len(values),
            "min": float(values.min()), "max": float(values.max()),
            "sha256": hashlib.sha256(content).hexdigest()}
    events = next(job for job in jobs if job["id"] == parent)["events"]
    assert {event["type"] for event in events} >= {"map_clear", "map_view", "map_layer"}
    assert any(event["type"] == "map_view" and event.get("zoom") == 12 for event in events)
    _, table = execute(TABLE_CODE, "table", "LOCAL_EE_PYTHON_TABLE_OK")
    output = next(job for job in request("/workbench/jobs").json() if job["id"] == table["export_id"])
    name = next(name for name in output["assets"] if name.endswith(".csv"))
    content = request(f"/workbench/jobs/{output['id']}/files/{name}").content
    (audit / "python-sdk-stats.csv").write_bytes(content)
    rows = list(csv.DictReader(io.StringIO(content.decode())))
    assert len(rows) == 1 and list(rows[0]) == ["NDVI"]
    assert np.isclose(float(rows[0]["NDVI"]), table["value"]["NDVI"], atol=1e-6, rtol=0)
    proof["table"] = {"getInfo": table["value"], "csv": rows[0], "passed": True}
    proof.update(passed=True, parent_id=parent, map_events=len(events),
        evidence_level="E; range/grid checks only, independent science recorded separately",
        google_service_comparison=False)
    (audit / "validation.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps({"passed": True, "sdk": proof["sdk"], "map_events": len(events), "raster": proof["raster"]}))


if __name__ == "__main__":
    run()
