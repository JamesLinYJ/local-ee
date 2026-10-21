"""Count and deny networking while trusted SDK introspection/probes execute.

This is test instrumentation for trusted code, not a sandbox for user scripts.
It measures the instrumented Python entry points, not packets or kernel egress.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import socket
from unittest.mock import patch

from gee.ee_python_transport import LocalEETransport


class OfflineViolation(AssertionError):
    """An offline generator attempted a transport or Python network operation."""


class OfflineGuard:
    def __init__(self):
        self.attempts = Counter()
        self.operations = []
        self._patches = ExitStack()

    def _deny(self, operation):
        def deny(*_args, **_kwargs):
            self.attempts[operation] += 1
            raise OfflineViolation(f"Offline generator attempted {operation}")
        return deny

    def __enter__(self):
        targets = [
            (LocalEETransport, "request", "local_transport.request"),
            (socket, "create_connection", "socket.create_connection"),
            (socket, "getaddrinfo", "socket.getaddrinfo"),
            (socket, "gethostbyname", "socket.gethostbyname"),
            (socket, "gethostbyname_ex", "socket.gethostbyname_ex"),
            (socket, "gethostbyaddr", "socket.gethostbyaddr"),
        ]
        targets.extend(
            (socket.socket, name, f"socket.socket.{name}")
            for name in ("connect", "connect_ex", "sendto", "sendmsg")
            if hasattr(socket.socket, name)
        )
        for owner, name, operation in targets:
            self._patches.enter_context(patch.object(owner, name, self._deny(operation)))
            self.operations.append(operation)
        return self

    def __exit__(self, error_type, error, traceback):
        self._patches.close()
        if error_type is None and self.attempts:
            raise OfflineViolation("Offline generator swallowed a denied network attempt")
        return False

    def evidence(self):
        return {
            "attempt_count": sum(self.attempts.values()),
            "attempts_by_operation": dict(sorted(self.attempts.items())),
            "instrumented_operations": sorted(self.operations),
            "mode": "deny_and_count_python_network_and_local_transport_entry_points",
            "scope": "Trusted in-process SDK probes only; not packet capture or kernel isolation",
        }
