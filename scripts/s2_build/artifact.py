"""Source fingerprints and atomic artifact publication for the S2 build."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile

from .dependencies import sha256


def adapter_sources(root: Path, lock_path: Path, build_script: Path,
                    build_helpers: list[Path]) -> list[Path]:
    native = root / "native/s2"
    cmake = native / "CMakeLists.txt"
    if not cmake.is_file():
        raise RuntimeError("native/s2/CMakeLists.txt is missing")
    sources = [path for path in native.glob("*") if path.is_file()
               and path.suffix.lower() in {".h", ".cpp"}]
    return sorted({cmake, lock_path, build_script, *build_helpers, *sources})


def source_hashes(root: Path, paths: list[Path]) -> dict[str, str]:
    result = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Adapter source is missing or symlinked: {path}")
        result[str(path.relative_to(root))] = sha256(path)
    return result


def publish_artifact(output_dir: Path, staged_library: Path, library_name: str,
                     lock_sha: str, source_snapshot: dict[str, str],
                     abi_version: int, platform_name: str,
                     machine: str, license_sources: dict[str, Path]) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise RuntimeError(f"Refusing to overwrite artifact directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staged_output = Path(tempfile.mkdtemp(prefix=".local-ee-s2-artifact-",
                                          dir=output_dir.parent))
    try:
        output_library = staged_output / library_name
        shutil.copyfile(staged_library, output_library)
        output_library.chmod(0o755)
        license_dir = staged_output / "licenses"
        license_dir.mkdir()
        licenses = {}
        for name, source in sorted(license_sources.items()):
            if Path(name).name != name or not source.is_file() or source.is_symlink():
                raise RuntimeError("Dependency license source is missing or not physical")
            target = license_dir / name
            shutil.copyfile(source, target)
            target.chmod(0o644)
            licenses[name] = sha256(target)
        manifest = {
            "schema": "local-ee-s2-artifact/v1",
            "abi_version": abi_version,
            "platform": platform_name,
            "machine": machine,
            "library": library_name,
            "library_sha256": sha256(output_library),
            "dependencies_lock_sha256": lock_sha,
            "sources": source_snapshot,
            "licenses": licenses,
        }
        manifest_path = staged_output / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
        manifest_path.chmod(0o600)
        if output_dir.exists() or output_dir.is_symlink():
            raise RuntimeError(f"Refusing to overwrite artifact directory: {output_dir}")
        os.rename(staged_output, output_dir)
    except Exception:
        shutil.rmtree(staged_output, ignore_errors=True)
        raise
    return manifest
