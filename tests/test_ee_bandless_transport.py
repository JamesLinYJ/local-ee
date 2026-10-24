"""Exercise the official SDK's local transport at a mocked HTTP byte boundary."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ee_bandless_reference import expected_pixels, load_fixture, local_metadata
from ee_bandless_sdk import load_python_example
from gee.ee_python_transport import LocalEETransport, LocalEETransportError
from scripts.ee_python_api.offline import OfflineGuard


def _rows(spec, values, fixture):
    transform = fixture["grid"]["transform"]
    return [
        {"feature": 0, "row": row, "col": col,
         "x": transform[0] * (col + 0.5) + transform[2],
         "y": transform[4] * (row + 0.5) + transform[5],
         "values": [values[band][row * fixture["grid"]["columns"] + col]
                    for band in spec["bands"]]}
        for row in range(fixture["grid"]["rows"])
        for col in range(fixture["grid"]["columns"])
    ]


def test_sdk_getinfo_map_and_export_cross_local_transport_without_tcp(
    tmp_path, monkeypatch,
):
    import ee
    import table_export_support as harness

    from engine.ee_sampling_result import SampledFeatureTable
    from gee import ee_python_tasks
    from gee.sampling_spec import decode_sampling_spec, sampling_columns
    from gee.sampling_values import assemble_sample_features
    from gee.services import ee as ee_service
    from table_export_support import FinishedTask, install

    fixture = load_fixture()
    catalog, items, *_ = local_metadata(fixture)
    values = expected_pixels(fixture)
    install_tasks_impl = ee_python_tasks.install_tasks
    captured = {}
    connections = []
    runtime = None
    csv_path = None

    class FakeResponse:
        def __init__(self, status, payload):
            self.status = status
            self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def read(self, limit):
            return self.body[:limit]

    class FakeHTTPConnection:
        def __init__(self, host, port, **kwargs):
            self.host, self.port = host, port
            self.kwargs = kwargs
            self.closed = False
            self.payload = None
            self.response = None
            connections.append(self)

        def request(self, method, path, *, body, headers):
            assert method == "POST" and path == "/gee/v1/dispatch"
            assert int(headers["Content-Length"]) == len(body)
            assert headers["Connection"] == "close"
            assert headers["Authorization"].startswith("Bearer basic//")
            self.payload = json.loads(body)

        def getresponse(self):
            nonlocal csv_path
            assert runtime is not None and self.payload is not None
            try:
                if self.payload.get("action") == "result":
                    job = runtime.store.job(self.payload["job_id"], runtime.account["user_id"])
                    spec_text = job["context"]["sample_spec"]
                    spec = decode_sampling_spec(spec_text)
                    data = assemble_sample_features(
                        spec, _rows(spec, values, fixture),
                    )
                    table = SampledFeatureTable(data, sampling_columns(spec))
                    table.sample_spec = spec_text
                    table.sample_spec_verified = True
                    table.sample_operations = ()
                    table.sample_operation_work = 0
                    folder = tmp_path / "jobs" / job["id"] / "out"
                    folder.mkdir(parents=True)
                    table.write_assets(folder / "out")
                    csv_path = folder / "openEO.csv"
                    job["status"] = "running"
                    runtime.worker.finish(job, FinishedTask())
                payload = runtime.dispatch(self.payload)
                self.response = FakeResponse(200, payload)
            except Exception as error:
                self.response = FakeResponse(400, {"message": str(error)})
            return self.response

        def close(self):
            self.closed = True

    original_configure = harness.configure_local_ee
    transport_request = LocalEETransport.request

    def capture_configured_compute(*args, **kwargs):
        client = original_configure(*args, **kwargs)
        captured["client"] = client
        captured["compute_value"] = client.data.computeValue
        return client

    monkeypatch.setattr(harness, "configure_local_ee", capture_configured_compute)
    from gee import ee_python_transport
    monkeypatch.setattr(ee_python_transport.http.client, "HTTPConnection", FakeHTTPConnection)

    with OfflineGuard() as guard:
        # Permit the configured local adapter method under test. All socket,
        # DNS, and connect entry points remain denied; HTTPConnection is fake.
        with monkeypatch.context() as allow_transport:
            allow_transport.setattr(LocalEETransport, "request", transport_request)
            runtime = install(monkeypatch, tmp_path)
            assert captured["client"] is runtime.ee
            monkeypatch.setattr(runtime.ee.data, "computeValue", captured["compute_value"])
            monkeypatch.setattr(ee_service, "DATA", tmp_path)
            monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
            # The shared workflow harness normally routes task calls directly
            # to dispatch. Restore the official adapter installer and replace
            # that test-only hook so task requests also cross the byte boundary.
            monkeypatch.setattr(ee_python_tasks, "install_tasks", install_tasks_impl)
            del runtime.ee.data._local_ee_tasks_installed
            install_tasks_impl(
                runtime.ee, runtime.ee._local_ee_runtime["transport"].request,
                lambda value: runtime.ee.serializer.encode(value, for_cloud_api=False),
            )
            outputs = load_python_example().build_workflow(runtime.ee, fixture)

            empty_info = outputs["empty"].getInfo()
            assert empty_info["bands"] == []
            assert outputs["empty"].bandNames().getInfo() == []
            assert runtime.ee.Image().bandNames().getInfo() == ["constant"]
            assert outputs["science"].getInfo()["bands"] == [
                {"id": name} for name in fixture["reference"]["science_band_order"]
            ]

            with pytest.raises(LocalEETransportError,
                               match="Zero-band Images contain no raster bands"):
                runtime.ee.Map.addLayer(outputs["empty"], name="empty")
            assert len(runtime.store.rows) == 0
            task = runtime.ee.batch.Export.image.toDrive(
                image=outputs["empty"], description="zero-band",
            )
            with pytest.raises(ee.ee_exception.EEException,
                               match="Zero-band Images contain no raster bands"):
                task.start()
            assert len(runtime.store.rows) == 0

            sample_info = outputs["samples"].getInfo()
            assert len(sample_info["features"]) == 4
            assert len(runtime.store.rows) == 1
            assert next(iter(runtime.store.rows.values()))["status"] == "finished"

    assert guard.evidence()["attempt_count"] == 0
    assert connections and all(connection.closed for connection in connections)
    assert all((c.host, c.port) == ("127.0.0.1", 8787) for c in connections)
    assert all(c.payload is not None for c in connections)
    actions = [connection.payload["action"] for connection in connections]
    assert actions.count("evaluate") == 5
    assert actions.count("map") == actions.count("export_image") == 1
    assert actions.count("result") == 1
    for action in ("map", "export_image"):
        connection = next(c for c in connections if c.payload["action"] == action)
        response = json.loads(connection.response.body)
        assert connection.response.status == 400
        assert response["message"] == (
            "Zero-band Images contain no raster bands; add actual bands before "
            "raster computation or export"
        )
    assert csv_path is not None and csv_path.is_file()
    with csv_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    for index, row in enumerate(rows):
        feature = sample_info["features"][index]
        assert feature["id"] == f"f0_r{index // 2}_c{index % 2}"
        for band in fixture["reference"]["science_band_order"]:
            expected = values[band][index]
            assert row[band] == ("" if expected is None else str(expected))
            assert feature["properties"][band] == expected
