"""Integrity-checked local S2 bridge; no installation or networking at runtime."""
from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import platform
import stat
import sys
import threading

from .ir import fail
from .spherical_wire import MAX_WIRE_DOUBLES, decode_geometry, encode_geometry


ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = ROOT / "native/s2/artifacts"
_LOCK = threading.Lock()
_LOADED = None
_OPERATIONS = {
    "contains": 0, "containedIn": 1, "intersects": 2, "disjoint": 3,
    "intersection": 4, "union": 5, "difference": 6, "symmetricDifference": 7,
    "validate": 8,
}


def _physical(path, *, directory=False):
    try:
        mode = path.lstat().st_mode
    except OSError:
        fail("S2 adapter is unavailable; run the explicit locked build first")
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        fail("S2 adapter paths must be physical files and directories")
    # Checking only a leaf would accept a regular file reached through a
    # symlinked native/source directory. Recheck ancestors on cached calls too.
    for parent in path.parents:
        try:
            mode = parent.lstat().st_mode
        except OSError:
            fail("S2 adapter parent directory is unavailable")
        if not stat.S_ISDIR(mode):
            fail("S2 adapter parent directories must be physical")


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(paths):
    result = []
    for path in paths:
        _physical(path)
        metadata = path.stat()
        result.append((str(path), metadata.st_dev, metadata.st_ino,
                       metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns))
    return tuple(result)


def _source_names():
    native = ROOT / "native/s2"
    _physical(native, directory=True)
    names = {str(path.relative_to(ROOT)) for path in native.iterdir()
             if path.suffix in {".cpp", ".h"}}
    names.update({"native/s2/CMakeLists.txt", "native/s2/dependencies.lock.json",
                  "scripts/build_s2_adapter.py", "scripts/s2_build/__init__.py",
                  "scripts/s2_build/dependencies.py", "scripts/s2_build/artifact.py"})
    return names


def _load():
    global _LOADED
    with _LOCK:
        if _LOADED is not None:
            paths, fingerprint, source_names, function = _LOADED
            if _source_names() != source_names or _fingerprint(paths) != fingerprint:
                fail("S2 adapter changed after loading; rebuild and restart the process")
            return function
        _physical(ARTIFACT_DIR, directory=True)
        manifest_path = ARTIFACT_DIR / "manifest.json"
        _physical(manifest_path)
        if manifest_path.stat().st_size > 64_000:
            fail("S2 adapter manifest exceeds its size limit")
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            fail("S2 adapter manifest is invalid")
        if type(manifest) is not dict:
            fail("S2 adapter manifest must be an object")
        library_name = "liblocal_ee_s2.dylib" if sys.platform == "darwin" else "liblocal_ee_s2.so"
        if (manifest.get("schema") != "local-ee-s2-artifact/v1"
                or manifest.get("abi_version") != 1
                or manifest.get("platform") != sys.platform
                or manifest.get("machine") != platform.machine()
                or manifest.get("library") != library_name):
            fail("S2 adapter manifest does not match this platform and ABI")
        sources = manifest.get("sources")
        if type(sources) is not dict or not 3 <= len(sources) <= 30:
            fail("S2 adapter source manifest is invalid")
        expected = _source_names()
        if set(sources) != expected:
            fail("S2 adapter source manifest is incomplete")
        source_paths = [ROOT / name for name in sorted(expected)]
        library_path = ARTIFACT_DIR / library_name
        licenses = manifest.get("licenses")
        if (type(licenses) is not dict or set(licenses) != {
                "s2geometry-LICENSE", "s2geometry-NOTICE", "abseil_cpp-LICENSE"}):
            fail("S2 adapter dependency licenses are incomplete")
        license_paths = [ARTIFACT_DIR / "licenses" / name for name in sorted(licenses)]
        paths = [manifest_path, library_path, *source_paths, *license_paths]
        fingerprint = _fingerprint(paths)
        for name, path in zip(sorted(expected), source_paths):
            if _digest(path) != sources[name]:
                fail("S2 adapter sources changed; rebuild the locked adapter")
        if _digest(library_path) != manifest.get("library_sha256"):
            fail("S2 adapter library digest mismatch")
        for name, path in zip(sorted(licenses), license_paths):
            if _digest(path) != licenses[name]:
                fail("S2 adapter dependency license digest mismatch")
        if manifest.get("dependencies_lock_sha256") != sources["native/s2/dependencies.lock.json"]:
            fail("S2 adapter dependency attestation mismatch")
        if _fingerprint(paths) != fingerprint or _source_names() != expected:
            fail("S2 adapter changed during integrity verification")
        try:
            library = ctypes.CDLL(str(library_path))
            function = library.local_ee_s2_run
        except (OSError, AttributeError):
            fail("S2 adapter could not load its pinned C ABI")
        doubles = ctypes.POINTER(ctypes.c_double)
        function.argtypes = [ctypes.c_int, doubles, ctypes.c_size_t,
                             doubles, ctypes.c_size_t, doubles, ctypes.c_size_t,
                             ctypes.POINTER(ctypes.c_size_t), ctypes.c_char_p, ctypes.c_size_t]
        function.restype = ctypes.c_int
        function._owned_library = library
        if _fingerprint(paths) != fingerprint or _source_names() != expected:
            fail("S2 adapter changed during native loading")
        _LOADED = (paths, fingerprint, expected, function)
        return function


def run(operation, left, right=None, *, output_positions=0, output_children=0):
    """Call the trusted native kernel after the caller reserves all work."""
    if operation not in _OPERATIONS:
        fail("Unsupported S2 native operation")
    function = _load()
    left_wire = encode_geometry(left)
    right_wire = encode_geometry(right) if right is not None else [1, 0]
    left_array = (ctypes.c_double * len(left_wire))(*left_wire)
    right_array = (ctypes.c_double * len(right_wire))(*right_wire)
    predicate = _OPERATIONS[operation] < 4 or operation == "validate"
    if not predicate and (type(output_positions) is not int or type(output_children) is not int
                          or not 0 <= output_positions <= 10_000
                          or not 1 <= output_children <= 1_000):
        fail("S2 output requires a finite precharged reservation")
    capacity = 1 if predicate else min(
        MAX_WIRE_DOUBLES, 2 + 6 * output_children + 3 * output_positions,
    )
    output = (ctypes.c_double * capacity)()
    size = ctypes.c_size_t()
    error = ctypes.create_string_buffer(1024)
    code = function(_OPERATIONS[operation], left_array, len(left_wire),
                    right_array, len(right_wire), output, capacity,
                    ctypes.byref(size), error, len(error))
    if code != 0:
        fail("S2 spherical operation failed: " + error.value.decode("utf-8", errors="replace"))
    if size.value > capacity:
        fail("S2 native output exceeded its allocation")
    if predicate:
        if size.value != 1 or output[0] not in (0, 1):
            fail("S2 returned a malformed Boolean output")
        return bool(output[0])
    return decode_geometry(output[:size.value], output_positions=output_positions,
                           output_children=output_children)


def validate(geometry):
    """Validate after an explicit input/validation reservation by the caller."""
    if run("validate", geometry) is not True:
        fail("S2 geometry validation failed")
