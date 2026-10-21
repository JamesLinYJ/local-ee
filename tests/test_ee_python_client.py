import json
import importlib
from pathlib import Path
import sys

import pytest

from gee import ee_python_client as client
from gee.ee_python_client import LocalEEInitializationError
from gee.ee_python_transport import LocalEETransportError


TOKEN = "b" * 48
URL = "http://127.0.0.1:8787/openeo/1.2"
SIGNATURES = Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json"


class FakeResponse:
    status = 200

    def read(self, limit):
        return b'{"value":3}'[:limit]


class FakeConnection:
    def __init__(self, host, port, **kwargs):
        self.destination = (host, port, kwargs)
        self.calls = []
        self.closed = False

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))

    def getresponse(self):
        return FakeResponse()

    def close(self):
        self.closed = True


def test_pinned_signatures_are_verified_and_converted(tmp_path):
    signatures = client._load_signatures(SIGNATURES)
    assert len(signatures) == 991
    assert signatures["Image.add"]["returns"].startswith("Image")
    assert signatures["Image.add"]["args"][0]["name"] == "image1"

    bad = tmp_path / "bad-ee-signatures.json"
    bad.write_text('{"algorithms":[]}', encoding="utf-8")
    try:
        with pytest.raises(LocalEEInitializationError, match="failed verification"):
            client._load_signatures(bad)
    finally:
        bad.unlink(missing_ok=True)


def test_client_refuses_a_different_sdk_version(monkeypatch):
    import ee

    monkeypatch.setattr(ee, "__version__", "1.7.48")
    with pytest.raises(LocalEEInitializationError, match="SDK 1.7.49"):
        client.configure_local_ee(URL, TOKEN, signatures_path=SIGNATURES)


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


def test_offline_sdk_initialization_serialization_and_local_getinfo(
    monkeypatch, clean_ee_module
):
    ee = clean_ee_module
    from gee import ee_python_transport

    monkeypatch.setattr(
        ee.data._cloud_api_utils,
        "build_cloud_resource",
        lambda *_args, **_kwargs: pytest.fail("Cloud API discovery was attempted"),
    )
    calls = []

    def create_connection(host, port, **kwargs):
        connection = FakeConnection(host, port, **kwargs)
        calls.append(connection)
        return connection

    monkeypatch.setattr(ee_python_transport.http.client, "HTTPConnection", create_connection)

    local = client.configure_local_ee(URL, TOKEN, signatures_path=SIGNATURES)
    assert local is ee
    assert ee.__version__ == "1.7.49"
    assert ee.data.is_initialized()
    assert ee.data._get_state().cloud_api_resource is None
    assert ee.data._get_state().cloud_api_resource_raw is None
    assert ee.Initialize() is None
    assert ee.Initialize(url=URL) is None

    expression = ee.Image(1).add(2)
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    assert encoded["type"] == "CompoundValue"
    assert encoded["scope"][-1][1]["functionName"] == "Image.add"

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate("2023-01-01", "2023-02-01")
        .map(lambda image: image.normalizedDifference(["B8", "B4"]).rename("NDVI"))
    )
    collection_dag = json.dumps(ee.serializer.encode(collection, for_cloud_api=False))
    assert "Collection.filter" in collection_dag
    assert "Image.normalizedDifference" in collection_dag
    assert '"type": "Function"' in collection_dag
    assert expression.getInfo() == 3
    assert len(calls) == 1
    assert calls[0].destination[:2] == ("127.0.0.1", 8787)
    assert calls[0].calls[0][1] == "/gee/v1/dispatch"
    payload = json.loads(calls[0].calls[0][2]["body"])
    assert payload["action"] == "evaluate"
    assert payload["expression"]["type"] == "CompoundValue"
    assert calls[0].closed

    ee.Reset()
    assert not ee.data.is_initialized()
    ee.Initialize()
    assert ee.data.is_initialized()
    assert (
        ee.serializer.encode(ee.Number(4).add(5), for_cloud_api=False)["functionName"]
        == "Number.add"
    )

    with pytest.raises(LocalEEInitializationError, match="credentials"):
        ee.Initialize(credentials=None)
    with pytest.raises(LocalEEInitializationError, match="credentials"):
        ee.Initialize(project="not-local")
    with pytest.raises(LocalEEInitializationError, match="only this script"):
        ee.Initialize(url="http://127.0.0.1:8788/openeo/1.2")
    with pytest.raises(LocalEEInitializationError, match="disabled"):
        ee.Authenticate()
    with pytest.raises(LocalEEInitializationError, match="disabled"):
        ee.data.get_persistent_credentials()
    with pytest.raises(LocalEETransportError, match="disabled"):
        ee.data.getAsset("users/example/private")
    with pytest.raises(LocalEETransportError, match="disabled"):
        ee.data.initialize(cloud_api_base_url="https://earthengine.googleapis.com")


def test_getinfo_uses_sdk_exception_and_redacts_local_token(
    monkeypatch, clean_ee_module
):
    ee = clean_ee_module
    from gee import ee_python_transport

    class ErrorResponse:
        status = 400

        def read(self, _limit):
            return json.dumps({"message": "bad token " + TOKEN}).encode()

    class ErrorConnection(FakeConnection):
        def getresponse(self):
            return ErrorResponse()

    monkeypatch.setattr(
        ee_python_transport.http.client,
        "HTTPConnection",
        lambda host, port, **kwargs: ErrorConnection(host, port, **kwargs),
    )
    local = client.configure_local_ee(URL, TOKEN, signatures_path=SIGNATURES)
    with pytest.raises(ee.ee_exception.EEException) as error:
        local.Number(1).getInfo()
    assert TOKEN not in str(error.value)


def test_client_has_a_top_level_import_path_for_the_sandbox(monkeypatch):
    import importlib.util

    source = Path(client.__file__)
    directory = str(source.parent)
    monkeypatch.syspath_prepend(directory)
    spec = importlib.util.spec_from_file_location("ee_python_client", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ee_python_client"] = module
    try:
        spec.loader.exec_module(module)
        assert callable(module.configure_local_ee)
    finally:
        sys.modules.pop("ee_python_client", None)
