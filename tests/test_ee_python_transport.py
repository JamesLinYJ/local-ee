import json

import pytest

from gee import ee_python_transport as transport_module
from gee.ee_python_transport import LocalEETransport, LocalEETransportError


TOKEN = "a" * 48


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def read(self, limit):
        return self.payload[:limit]


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def install_connections(monkeypatch, responses):
    queued = list(responses)
    connections = []

    def create(host, port, **kwargs):
        connection = FakeConnection(queued.pop(0))
        connection.destination = (host, port, kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(transport_module.http.client, "HTTPConnection", create)
    return connections


def response(value, status=200):
    return FakeResponse(json.dumps(value).encode(), status)


def test_transport_posts_only_to_fixed_local_dispatch_path_and_ignores_proxy(monkeypatch):
    connections = install_connections(monkeypatch, [response({"value": 7})])
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    result = LocalEETransport("http://127.0.0.1:8787/openeo/1.2", TOKEN).request(
        {"action": "evaluate", "expression": {}}
    )
    assert result == {"value": 7}
    method, path, kwargs = connections[0].calls[0]
    assert connections[0].destination[:2] == ("127.0.0.1", 8787)
    assert method == "POST" and path == "/gee/v1/dispatch"
    assert kwargs["headers"]["Authorization"] == "Bearer basic//" + TOKEN
    assert json.loads(kwargs["body"]) == {"action": "evaluate", "expression": {}}
    assert connections[0].closed


@pytest.mark.parametrize(
    "url",
    [
        "https://earthengine.googleapis.com",
        "http://localhost:8787",
        "http://127.0.0.1.evil.example:8787",
        "http://user:pass@127.0.0.1:8787",
        "http://127.0.0.1:8787/openeo/1.2?redirect=1",
        "http://127.0.0.1:8787/gee/v1/dispatch",
    ],
)
def test_transport_rejects_nonlocal_or_ambiguous_url(url):
    with pytest.raises(ValueError, match="loopback"):
        LocalEETransport(url, TOKEN)


def test_transport_rejects_port_zero():
    with pytest.raises(ValueError, match="port"):
        LocalEETransport("http://127.0.0.1:0", TOKEN)


def test_transport_rejects_redirect_without_following_it(monkeypatch):
    connections = install_connections(
        monkeypatch, [FakeResponse(b"", status=302), response({"followed": True})]
    )
    with pytest.raises(LocalEETransportError, match="redirect"):
        LocalEETransport("http://127.0.0.1:8787", TOKEN).request(
            {"action": "evaluate"}
        )
    assert len(connections) == 1
    assert connections[0].closed


def test_transport_limits_encoded_payload_before_network(monkeypatch):
    connections = install_connections(monkeypatch, [])
    transport = LocalEETransport("http://127.0.0.1:8787", TOKEN, max_bytes=64)
    with pytest.raises(ValueError, match="1 MiB limit"):
        transport.request({"action": "evaluate", "expression": "x" * 80})
    assert connections == []


def test_transport_limits_response_size(monkeypatch):
    install_connections(monkeypatch, [FakeResponse(b"x" * 128)])
    with pytest.raises(LocalEETransportError, match="1 MiB limit"):
        LocalEETransport("http://127.0.0.1:8787", TOKEN, max_bytes=64).request(
            {"action": "evaluate"}
        )


def test_transport_polls_pending_evaluations_until_value(monkeypatch):
    connections = install_connections(
        monkeypatch,
        [
            response({"pending": True, "job_id": "local-job"}),
            response({"value": {"ok": True}}),
        ],
    )
    result = LocalEETransport(
        "http://127.0.0.1:8787", TOKEN, evaluation_timeout_s=2, poll_interval_s=0
    ).request({"action": "evaluate", "expression": {}})
    assert result == {"value": {"ok": True}}
    assert len(connections) == 2
    assert json.loads(connections[1].calls[0][2]["body"]) == {
        "action": "result",
        "job_id": "local-job",
    }


def test_transport_redacts_token_from_api_error(monkeypatch):
    install_connections(
        monkeypatch, [response({"message": f"bad {TOKEN}"}, status=400)]
    )
    with pytest.raises(LocalEETransportError) as error:
        LocalEETransport("http://127.0.0.1:8787", TOKEN).request(
            {"action": "evaluate"}
        )
    assert TOKEN not in str(error.value)
