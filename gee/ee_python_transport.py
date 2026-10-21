"""Bounded local-only transport for the official Earth Engine Python client."""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import ssl
import time
from urllib.parse import urlsplit


_TOKEN = re.compile(r"^[A-Za-z0-9._~-]{20,512}$")


class LocalEETransportError(RuntimeError):
    """A bounded local API failure with no request secrets in its message."""


class LocalEETransport:
    """Send EE dispatch requests directly to the configured loopback API."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        request_timeout_s: float = 30.0,
        evaluation_timeout_s: float = 100.0,
        max_bytes: int = 1_048_576,
        poll_interval_s: float = 1.0,
    ):
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError("Local EE API URL is invalid")
        parsed = urlsplit(url)
        host = parsed.hostname
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except (TypeError, ValueError):
            loopback = False
        if (
            parsed.scheme not in {"http", "https"}
            or not loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/", "/openeo/1.2", "/gee/v1"}
        ):
            raise ValueError("Local EE API must be a loopback URL")
        try:
            port = parsed.port
            if port is None:
                port = 443 if parsed.scheme == "https" else 80
        except ValueError as error:
            raise ValueError("Local EE API URL has an invalid port") from error
        if not 1 <= port <= 65535:
            raise ValueError("Local EE API URL has an invalid port")
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ValueError("Local EE script token is invalid")
        if request_timeout_s <= 0 or evaluation_timeout_s <= 0 or max_bytes < 1:
            raise ValueError("Local EE transport limits must be positive")
        if poll_interval_s < 0:
            raise ValueError("Local EE polling interval cannot be negative")

        self._scheme = parsed.scheme
        self._host = host
        self._port = port
        self._token = token
        self._request_timeout_s = float(request_timeout_s)
        self._evaluation_timeout_s = float(evaluation_timeout_s)
        self._max_bytes = int(max_bytes)
        self._poll_interval_s = float(poll_interval_s)

    def request(self, payload: dict) -> dict:
        """Dispatch one request, waiting within a fixed budget for getInfo."""
        encoded = self._encode(payload)
        if payload.get("action") != "evaluate":
            return self._post(encoded, self._request_timeout_s)

        deadline = time.monotonic() + self._evaluation_timeout_s
        response = self._post(encoded, self._remaining(deadline))
        warnings = response.get("warnings", [])
        while response.get("pending") is True:
            job_id = response.get("job_id")
            if not isinstance(job_id, str) or not job_id or len(job_id) > 128:
                raise LocalEETransportError("Local EE evaluation returned an invalid task")
            remaining = self._remaining(deadline)
            if self._poll_interval_s:
                time.sleep(min(self._poll_interval_s, remaining))
            response = self._post(
                self._encode({"action": "result", "job_id": job_id}),
                self._remaining(deadline),
            )
        if warnings and isinstance(response, dict) and "warnings" not in response:
            response["warnings"] = warnings
        return response

    def _encode(self, payload: dict) -> bytes:
        if not isinstance(payload, dict):
            raise ValueError("Local EE request must be an object")
        try:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("Local EE request is not valid JSON") from error
        if len(body) > self._max_bytes:
            raise ValueError("Local EE request exceeds the 1 MiB limit")
        return body

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LocalEETransportError("Local EE evaluation exceeded its time limit")
        return min(self._request_timeout_s, remaining)

    def _post(self, body: bytes, timeout_s: float) -> dict:
        connection_type = (
            http.client.HTTPSConnection
            if self._scheme == "https"
            else http.client.HTTPConnection
        )
        kwargs = {"timeout": timeout_s}
        if self._scheme == "https":
            kwargs["context"] = ssl.create_default_context()
        connection = connection_type(self._host, self._port, **kwargs)
        try:
            connection.request(
                "POST",
                "/gee/v1/dispatch",
                body=body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": "Bearer basic//" + self._token,
                    "Content-Length": str(len(body)),
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            raw = response.read(self._max_bytes + 1)
            if len(raw) > self._max_bytes:
                raise LocalEETransportError("Local EE response exceeds the 1 MiB limit")
            if 300 <= response.status < 400:
                raise LocalEETransportError("Local EE redirects are disabled")
            try:
                result = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise LocalEETransportError("Local EE returned invalid JSON") from None
            if not isinstance(result, dict):
                raise LocalEETransportError("Local EE returned an invalid response")
            if response.status < 200 or response.status >= 300:
                message = result.get("message") or result.get("error")
                if not isinstance(message, str):
                    message = f"Local EE API returned HTTP {response.status}"
                message = message.replace(self._token, "[redacted]")
                message = message.replace("basic//" + self._token, "[redacted]")
                raise LocalEETransportError(message[:500])
            return result
        except LocalEETransportError:
            raise
        except (OSError, http.client.HTTPException, TimeoutError):
            raise LocalEETransportError("Local EE request failed or timed out") from None
        finally:
            connection.close()
