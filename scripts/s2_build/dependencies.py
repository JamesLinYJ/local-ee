"""Locked archive acquisition and safe extraction for the S2 build."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import time
import urllib.error
import urllib.request
import zipfile


DOWNLOAD_HOSTS = {"github.com", "codeload.github.com"}
CHUNK_BYTES = 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    lock = json.loads(raw)
    if lock.get("schema") != "local-ee-s2-dependency-lock/v1":
        raise RuntimeError("Unrecognized S2 dependency lock schema")
    for name, source in lock.get("sources", {}).items():
        if len(source.get("sha256", "")) != 64:
            raise RuntimeError(f"Missing SHA-256 pin for {name}")
    return lock, hashlib.sha256(raw).hexdigest()


class _LockedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, new_url):
        from urllib.parse import urlparse

        parsed = urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS:
            raise urllib.error.URLError("Archive redirected outside the locked GitHub hosts")
        return super().redirect_request(req, fp, code, msg, headers, new_url)


def download_archive(name: str, source: dict, cache: Path, offline: bool,
                     max_bytes: int, timeout_seconds: int) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    suffix = ".tar.gz" if source["archive_format"] == "tar.gz" else ".zip"
    destination = cache / f"{name}-{source['version']}{suffix}"
    expected = source["sha256"]
    if destination.exists():
        if destination.stat().st_size > max_bytes or sha256(destination) != expected:
            raise RuntimeError(f"Cached {name} archive does not match its locked hash")
        print(f"  using verified archive: {destination}", flush=True)
        return destination
    if offline:
        raise RuntimeError(f"--offline requested but archive is missing: {destination}")

    partial = cache / f".{destination.name}.{os.getpid()}.partial"
    request = urllib.request.Request(
        source["archive_url"],
        headers={"User-Agent": "local-ee-s2-build/1", "Accept-Encoding": "identity"},
    )
    started = time.monotonic()
    total = 0
    try:
        opener = urllib.request.build_opener(_LockedRedirectHandler())
        with opener.open(request, timeout=min(45, timeout_seconds)) as response:
            from urllib.parse import urlparse

            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in DOWNLOAD_HOSTS:
                raise RuntimeError("Archive response did not come from an allowed HTTPS host")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise RuntimeError(f"{name} archive exceeds the locked size limit")
            with partial.open("xb") as output:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError(f"{name} archive exceeds the locked size limit")
                    if time.monotonic() - started > timeout_seconds:
                        raise TimeoutError(f"Timed out downloading {name}")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if sha256(partial) != expected:
            raise RuntimeError(f"Downloaded {name} archive SHA-256 mismatch")
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    print(f"  fetched and verified {name} ({total} bytes, {time.monotonic() - started:.1f}s)",
          flush=True)
    return destination


def _safe_parts(name: str, expected_root: str) -> tuple[str, ...]:
    if not name or "\\" in name or name.startswith("/"):
        raise RuntimeError(f"Unsafe archive path: {name!r}")
    raw_parts = name.rstrip("/").split("/")
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise RuntimeError(f"Unsafe archive path: {name!r}")
    parts = PurePosixPath(name).parts
    if not parts or parts[0] != expected_root:
        raise RuntimeError(f"Unexpected archive root for member: {name!r}")
    return parts


def _write_member(destination: Path, parts: tuple[str, ...], source, size: int,
                  executable: bool) -> None:
    path = destination.joinpath(*parts)
    if not path.resolve().is_relative_to(destination.resolve()):
        raise RuntimeError("Archive member escaped the extraction directory")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    remaining = size
    with path.open("xb") as output:
        while remaining:
            chunk = source.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise RuntimeError(f"Truncated archive member: {path.name}")
            output.write(chunk)
            remaining -= len(chunk)
        if source.read(1):
            raise RuntimeError(f"Archive member exceeded its declared size: {path.name}")
    path.chmod(0o700 if executable else 0o600)


def safe_extract_tar(archive: Path, destination: Path, root_name: str,
                     max_bytes: int, max_members: int) -> Path:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    seen: set[tuple[str, ...]] = set()
    total = 0
    try:
        member_count = 0
        with tarfile.open(archive, "r|gz") as bundle:
            for member in bundle:
                member_count += 1
                if member_count > max_members:
                    raise RuntimeError("Tar archive has too many members")
                parts = _safe_parts(member.name, root_name)
                if parts in seen:
                    raise RuntimeError(f"Duplicate archive member: {member.name}")
                seen.add(parts)
                path = destination.joinpath(*parts)
                if not path.resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("Tar member escaped the extraction directory")
                if member.isdir():
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                if not member.isfile() or member.size < 0:
                    raise RuntimeError(f"Tar links and special files are forbidden: {member.name}")
                total += member.size
                if total > max_bytes:
                    raise RuntimeError("Tar archive exceeds the extracted byte limit")
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"Cannot read tar member: {member.name}")
                with source:
                    _write_member(path.parent, (path.name,), source, member.size,
                                  bool(member.mode & 0o111))
        root = destination / root_name
        if not root.is_dir():
            raise RuntimeError(f"Archive did not contain expected root: {root_name}")
        return root
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def safe_extract_zip(archive: Path, destination: Path, root_name: str,
                     max_bytes: int, max_members: int) -> Path:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    seen: set[tuple[str, ...]] = set()
    total = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > max_members:
                raise RuntimeError("Zip archive has too many members")
            for member in members:
                parts = _safe_parts(member.filename, root_name)
                if parts in seen:
                    raise RuntimeError(f"Duplicate archive member: {member.filename}")
                seen.add(parts)
                if member.flag_bits & 1:
                    raise RuntimeError(f"Encrypted zip member is forbidden: {member.filename}")
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                is_dir = member.is_dir()
                if kind == stat.S_IFLNK or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise RuntimeError(f"Zip links and special files are forbidden: {member.filename}")
                path = destination.joinpath(*parts)
                if not path.resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("Zip member escaped the extraction directory")
                if is_dir:
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                total += member.file_size
                if total > max_bytes:
                    raise RuntimeError("Zip archive exceeds the extracted byte limit")
                with bundle.open(member) as source:
                    _write_member(path.parent, (path.name,), source, member.file_size,
                                  bool(mode & 0o111))
        root = destination / root_name
        if not root.is_dir():
            raise RuntimeError(f"Archive did not contain expected root: {root_name}")
        return root
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
