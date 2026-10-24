"""Adapter integrity controls; fake CDLL never executes fixture bytes."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from gee.compat.earthengine import spherical_native as native
from gee.compat.earthengine.ir import UnsupportedEEError


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    folder = root / "native/s2/artifacts"
    folder.mkdir(parents=True)
    names = ["native/s2/adapter.cpp", "native/s2/CMakeLists.txt",
             "native/s2/dependencies.lock.json", "scripts/build_s2_adapter.py",
             "scripts/s2_build/__init__.py", "scripts/s2_build/dependencies.py",
             "scripts/s2_build/artifact.py"]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("inert source fixture\n")
    library_name = "liblocal_ee_s2.dylib" if sys.platform == "darwin" else "liblocal_ee_s2.so"
    library = folder / library_name
    library.write_bytes(b"inert bytes, never passed to the real CDLL")
    hashes = {name: digest(root / name) for name in names}
    manifest = folder / "manifest.json"
    license_dir = folder / "licenses"
    license_dir.mkdir()
    licenses = {}
    for name in ("s2geometry-LICENSE", "s2geometry-NOTICE", "abseil_cpp-LICENSE"):
        path = license_dir / name
        path.write_text("inert license fixture")
        licenses[name] = digest(path)
    manifest.write_text(json.dumps({
        "schema": "local-ee-s2-artifact/v1", "abi_version": 1,
        "platform": sys.platform, "machine": platform.machine(), "library": library_name,
        "library_sha256": digest(library), "sources": hashes,
        "dependencies_lock_sha256": hashes["native/s2/dependencies.lock.json"],
        "licenses": licenses,
    }))
    calls = []

    def inert_cdll(path):
        calls.append(path)
        return SimpleNamespace(local_ee_s2_run=SimpleNamespace())

    monkeypatch.setattr(native, "ROOT", root)
    monkeypatch.setattr(native, "ARTIFACT_DIR", folder)
    monkeypatch.setattr(native, "_LOADED", None)
    monkeypatch.setattr(native.ctypes, "CDLL", inert_cdll)
    return SimpleNamespace(root=root, folder=folder, library=library, manifest=manifest,
                           source=root / names[0], calls=calls)


def test_exact_valid_manifest_loads_once_and_reuses_the_verified_handle(artifact):
    function = native._load()
    assert native._load() is function
    assert artifact.calls == [str(artifact.library)]


@pytest.mark.parametrize("target", ["manifest", "source", "library"])
def test_changed_file_after_load_invalidates_the_handle(artifact, target):
    native._load()
    getattr(artifact, target).write_text("changed contents")
    with pytest.raises(UnsupportedEEError, match="changed after loading"):
        native._load()
    assert len(artifact.calls) == 1


@pytest.mark.parametrize("target", ["source", "library"])
def test_digest_mismatch_is_rejected_before_native_loading(artifact, target):
    getattr(artifact, target).write_text("changed contents")
    with pytest.raises(UnsupportedEEError, match="digest mismatch|sources changed"):
        native._load()
    assert artifact.calls == []


@pytest.mark.parametrize("value", [[], None, 12, "manifest"])
def test_manifest_must_be_an_object(artifact, value):
    artifact.manifest.write_text(json.dumps(value))
    with pytest.raises(UnsupportedEEError, match="manifest must be an object"):
        native._load()
    assert artifact.calls == []


def test_adding_source_after_loading_invalidates_the_source_set(artifact):
    native._load()
    (artifact.source.parent / "new.cpp").write_text("new source")
    with pytest.raises(UnsupportedEEError, match="changed after loading"):
        native._load()
    assert len(artifact.calls) == 1


@pytest.mark.parametrize("target", ["library", "source"])
def test_symlinked_file_is_rejected_before_loading(artifact, target):
    path = getattr(artifact, target)
    moved = path.with_name(path.name + ".physical")
    path.rename(moved)
    path.symlink_to(moved.name)
    with pytest.raises(UnsupportedEEError, match="physical"):
        native._load()
    assert artifact.calls == []


def test_symlinked_ancestor_is_rejected_before_loading(artifact):
    directory = artifact.root / "native"
    moved = artifact.root / "physical-native"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    with pytest.raises(UnsupportedEEError, match="physical"):
        native._load()
    assert artifact.calls == []


def test_file_change_after_hashing_never_reaches_cdll(artifact, monkeypatch):
    original = native._digest

    def change_after_read(path):
        result = original(path)
        if path == artifact.library:
            path.write_text("changed after its digest was read")
        return result

    monkeypatch.setattr(native, "_digest", change_after_read)
    with pytest.raises(UnsupportedEEError, match="during integrity verification"):
        native._load()
    assert artifact.calls == []
