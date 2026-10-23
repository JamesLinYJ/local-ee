"""Bounded subprocess helper for trusted native-kernel probes."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time


_MAX_CAPTURE_BYTES = 1_000_000


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait()


def run_bounded(command: list[str], *, cwd: str, timeout: float,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run one command with bounded time/output and cleanup of its owned process group."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    streams = {"stdout": process.stdout, "stderr": process.stderr}
    buffers = {name: bytearray() for name in streams}
    for name, stream in streams.items():
        assert stream is not None
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError(f"process exceeded {timeout:.0f}s")
            for key, _ in selector.select(min(remaining, 0.5)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                buffers[key.data].extend(chunk)
                if sum(map(len, buffers.values())) > _MAX_CAPTURE_BYTES:
                    raise RuntimeError(f"process output exceeded {_MAX_CAPTURE_BYTES} bytes")
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise TimeoutError(f"process exceeded {timeout:.0f}s")
        returncode = process.wait(timeout=remaining)
    except (TimeoutError, RuntimeError) as error:
        _kill_process_group(process)
        stdout = bytes(buffers["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(buffers["stderr"]).decode("utf-8", errors="replace")
        raise RuntimeError(f"{error}; stdout={stdout!r}; stderr={stderr!r}") from error
    except subprocess.TimeoutExpired as error:
        _kill_process_group(process)
        stdout = bytes(buffers["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(buffers["stderr"]).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"process wait exceeded {timeout:.0f}s; stdout={stdout!r}; stderr={stderr!r}"
        ) from error
    finally:
        if process.poll() is None:
            _kill_process_group(process)
        selector.close()
        for stream in streams.values():
            if stream is not None and not stream.closed:
                stream.close()

    return subprocess.CompletedProcess(
        command,
        returncode,
        bytes(buffers["stdout"]).decode("utf-8", errors="replace"),
        bytes(buffers["stderr"]).decode("utf-8", errors="replace"),
    )
