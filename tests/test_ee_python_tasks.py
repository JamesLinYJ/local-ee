"""Contract tests for the pinned SDK's local export, status and map hooks."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_local_image_options_normalize_integral_float_pixel_limits():
    import ee
    from gee.ee_python_exports import local_options

    for value, expected in (
        (100_000_000.0, 100_000_000),
        (1e13, 10_000_000_000_000),
    ):
        result = local_options(
            ee,
            "export_image",
            {"expression": object(), "fileFormat": "GeoTIFF", "maxPixels": value},
            lambda item: item,
        )
        assert result["options"]["maxPixels"] == expected
        assert isinstance(result["options"]["maxPixels"], int)

    for value in (1.5, -1, float("nan"), float("inf"), True, 2**53, 10**500):
        with pytest.raises(ee.ee_exception.EEException, match="maxPixels"):
            local_options(
                ee,
                "export_image",
                {"expression": object(), "fileFormat": "GeoTIFF", "maxPixels": value},
                lambda item: item,
            )


@pytest.fixture
def clean_ee_module():
    import ee

    def reset():
        ee.Reset()
        for name in ("_local_ee_runtime", "Map"):
            if hasattr(ee, name):
                delattr(ee, name)
        if hasattr(ee.data, "_local_ee_tasks_installed"):
            del ee.data._local_ee_tasks_installed
        importlib.reload(ee.data)
        importlib.reload(ee.oauth)
        importlib.reload(ee)

    reset()
    yield ee
    reset()


def test_official_python_task_and_map_apis_use_local_dispatch(
    monkeypatch, clean_ee_module
):
    ee = clean_ee_module
    import gee.ee_python_client as client

    requests = []
    jobs = {}
    fail_next = []

    def dispatch(payload):
        requests.append(payload)
        action = payload["action"]
        if fail_next and fail_next[0] == action:
            fail_next.pop()
            raise RuntimeError("sample local dispatch failure")
        if action in {"export_image", "export_table", "map"}:
            job_id = f"local-{len(jobs) + 1}"
            options = payload.get("options", {})
            jobs[job_id] = {
                "state": "created" if action.startswith("export_") else "queued",
                "description": options.get("description") or options.get("name"),
                "task_type": "EXPORT_IMAGE" if action != "export_table" else "EXPORT_FEATURES",
            }
            return {"job_id": job_id, "warnings": []}
        if action == "start":
            jobs[payload["job_id"]]["state"] = "queued"
            return {"value": {"id": payload["job_id"], "state": "READY"}}
        if action == "status":
            row = jobs[payload["job_id"]]
            state = {
                "created": "UNSUBMITTED",
                "queued": "READY",
                "running": "RUNNING",
                "finished": "COMPLETED",
                "error": "FAILED",
                "canceled": "CANCELLED",
            }[row["state"]]
            return {
                "value": {
                    "id": payload["job_id"],
                    "state": state,
                    "description": row["description"],
                    "task_type": row["task_type"],
                    "error_message": "sample failure" if state == "FAILED" else None,
                }
            }
        if action == "cancel":
            jobs[payload["job_id"]]["state"] = "canceled"
            return {"value": {"id": payload["job_id"], "state": "CANCELLED"}}
        if action == "list":
            operations = []
            for job_id, row in jobs.items():
                if row["state"] in {"created", "queued", "running", "finished", "error", "canceled"}:
                    task_state = {
                        "created": "PENDING",
                        "queued": "PENDING",
                        "running": "RUNNING",
                        "finished": "SUCCEEDED",
                        "error": "FAILED",
                        "canceled": "CANCELLED",
                    }[row["state"]]
                    operations.append(
                        {
                            "name": "operations/" + job_id,
                            "metadata": {
                                "state": task_state,
                                "description": row["description"],
                                "type": row["task_type"],
                            },
                            "done": row["state"] in {"finished", "error", "canceled"},
                        }
                    )
            return {"operations": operations}
        if action in {"map_clear", "map_view", "map_zoom"}:
            return {"value": True}
        raise AssertionError(f"Unexpected local EE action: {action}")

    class FakeTransport:
        def __init__(self, *_args, **_kwargs):
            self.request = dispatch

    monkeypatch.setattr(client, "LocalEETransport", FakeTransport)
    ee = client.configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json"
    )

    image = ee.Image.constant(3)
    region = ee.Geometry.Polygon(
        [[[100, 30], [101, 30], [101, 31], [100, 30]]]
    )
    task = ee.batch.Export.image.toDrive(
        image,
        description="python-local-export",
        folder="research",
        fileNamePrefix="ndvi",
        region=region,
        scale=10,
        crs="EPSG:32649",
        maxPixels=1e8,
    )
    task.start()
    task.start()  # The same official Task must not create duplicate local jobs.
    assert task.id == "local-1"
    assert task.operation_name == "operations/local-1"
    assert task.status()["state"] == ee.batch.Task.State.READY
    assert [call["action"] for call in requests[:3]] == [
        "export_image",
        "status",
        "start",
    ]
    export = requests[0]
    assert export["expression"]["functionName"] == "Image.constant"
    assert export["options"] == {
        "description": "python-local-export",
        "folder": "research",
        "fileNamePrefix": "ndvi",
        "fileFormat": "GeoTIFF",
        "region": {
            "type": "Polygon",
            "coordinates": [[[100, 30], [101, 30], [101, 31], [100, 30]]],
            "evenOdd": True,
        },
        "scale": 10,
        "crs": "EPSG:32649",
        "maxPixels": 100_000_000,
    }
    assert "Image.clipToBoundsAndScale" not in str(export["expression"])
    assert isinstance(export["request_id"], str)

    jobs[task.id]["state"] = "running"
    assert task.status()["state"] == ee.batch.Task.State.RUNNING
    task.cancel()
    assert task.status()["state"] == ee.batch.Task.State.CANCELLED
    assert task.id in {listed.id for listed in ee.batch.Task.list()}

    map_layer = ee.Map.addLayer(image, {"min": 0, "max": 5}, "NDVI", False, 0.6)
    assert map_layer["job_id"] == "local-2"
    local_map_id = image.getMapId({"min": 0, "max": 5})
    assert local_map_id["mapid"] == "local:local-3"
    assert local_map_id["pending"] is True
    assert local_map_id["local"] is True
    assert "tile_fetcher" not in local_map_id

    ee.Map.centerObject(ee.Geometry.Point(100, 30), 8)
    ee.Map.setCenter(101, 31, 9)
    ee.Map.setZoom(10)
    ee.Map.clear()
    assert [call["action"] for call in requests[-4:]] == [
        "map_view",
        "map_view",
        "map_zoom",
        "map_clear",
    ]
    assert requests[-2]["options"] == {"zoom": 10}

    table = ee.FeatureCollection(
        [ee.Feature(ee.Geometry.Point(100, 30), {"name": "site-a"})]
    )
    table_task = ee.batch.Export.table.toDrive(
        table,
        description="python-local-table",
        folder="research",
        fileNamePrefix="sites",
        selectors=["name"],
    )
    table_task.start()
    table_export = requests[-3]
    assert table_export["action"] == "export_table"
    assert table_export["options"] == {
        "description": "python-local-table",
        "folder": "research",
        "fileNamePrefix": "sites",
        "fileFormat": "CSV",
        "selectors": ["name"],
    }
    assert table_task.id == "local-4"

    fail_next.append("export_image")
    with pytest.raises(ee.ee_exception.EEException, match="sample local dispatch failure"):
        ee.batch.Export.image.toDrive(image, description="failed-dispatch").start()

    with pytest.raises(ee.ee_exception.EEException, match="toDrive"):
        ee.batch.Export.image.toCloudStorage(image, bucket="unused")
    with pytest.raises(ee.ee_exception.EEException, match="crs_transform"):
        ee.batch.Export.image.toDrive(
            image, crs="EPSG:32649", crsTransform=[10, 0, 0, 0, -10, 0]
        )

    large_task = ee.batch.Export.image.toDrive(
        image, description="large-pixel-limit", maxPixels=1e13
    )
    large_task.start()
    assert requests[-3]["action"] == "export_image"
    assert requests[-3]["options"]["maxPixels"] == 10_000_000_000_000
    for invalid_max_pixels in (
        1.5,
        -1,
        float("nan"),
        float("inf"),
        True,
        2**53,
        10**500,
    ):
        with pytest.raises(ee.ee_exception.EEException, match="maxPixels"):
            ee.batch.Export.image.toDrive(image, maxPixels=invalid_max_pixels)
    assert all(
        call["action"] not in {"exportMap", "exportVideo", "exportClassifier"}
        for call in requests
    )
