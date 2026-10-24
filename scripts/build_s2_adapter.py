#!/usr/bin/env python3
"""Build the pinned local S2 C ABI adapter into a new artifact directory.

Downloads are build-time only. Sources, CMake state, logs, and the staged static
dependency install stay under the required --work-dir. Output is published only
after compilation and source-hash readback succeed.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import zipfile

from s2_build.artifact import adapter_sources, publish_artifact, source_hashes
from s2_build.dependencies import (
    download_archive,
    load_lock,
    safe_extract_tar,
    safe_extract_zip,
)


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "native/s2/dependencies.lock.json"
BUILD_SCRIPT = Path(__file__).resolve()
BUILD_HELPERS = [
    ROOT / "scripts/s2_build/__init__.py",
    ROOT / "scripts/s2_build/dependencies.py",
    ROOT / "scripts/s2_build/artifact.py",
]


def run_step(label: str, command: list[str], cwd: Path, log_path: Path,
             timeout_seconds: int) -> float:
    print(f"  started {label}", flush=True)
    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} exceeded {timeout_seconds}s; log: {log_path}") from exc
    except subprocess.CalledProcessError as exc:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
        raise RuntimeError(f"{label} failed; log: {log_path}\n" + "\n".join(tail)) from exc
    elapsed = time.monotonic() - started
    print(f"  finished {label} in {elapsed:.1f}s", flush=True)
    return elapsed


def cmake_version() -> tuple[str, tuple[int, int, int]]:
    result = subprocess.run(["cmake", "--version"], check=True, capture_output=True,
                            text=True, timeout=15)
    version_text = result.stdout.splitlines()[0].rsplit(" ", 1)[-1]
    parts = tuple(int(value) for value in version_text.split(".")[:3])
    return version_text, (*parts, *(0 for _ in range(3 - len(parts))))


def build(args: argparse.Namespace) -> dict:
    lock, lock_sha = load_lock(LOCK_PATH)
    limits = lock["limits"]
    if not 1 <= args.jobs <= limits["max_build_jobs"]:
        raise RuntimeError(f"--jobs must be between 1 and {limits['max_build_jobs']}")
    sources = adapter_sources(ROOT, LOCK_PATH, BUILD_SCRIPT, BUILD_HELPERS)
    # Attest the code that actually began this build, including download and
    # publication helpers, rather than taking a new snapshot after compiling.
    source_snapshot = source_hashes(ROOT, sources)

    work_dir = args.work_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    native_dir = ROOT / "native/s2"
    if work_dir == ROOT or work_dir == native_dir or native_dir in work_dir.parents:
        raise RuntimeError("--work-dir must be a separate scratch directory outside native/s2")
    if work_dir == output_dir or work_dir in output_dir.parents or output_dir in work_dir.parents:
        raise RuntimeError("--work-dir and --output-dir must not contain one another")
    if output_dir.exists() or output_dir.is_symlink():
        raise RuntimeError(f"Refusing to overwrite existing output directory: {output_dir}")
    work_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        library_name = "liblocal_ee_s2.dylib"
    elif sys.platform.startswith("linux"):
        library_name = "liblocal_ee_s2.so"
    else:
        raise RuntimeError(f"Unsupported build platform: {sys.platform}")

    cmake_text, cmake_parts = cmake_version()
    minimum = tuple(int(part) for part in lock["build"]["cmake_minimum_version"].split("."))
    if cmake_parts < minimum:
        raise RuntimeError(f"CMake {cmake_text} is older than required {minimum}")

    run_dir = Path(tempfile.mkdtemp(prefix=f"s2-{lock_sha[:12]}-", dir=work_dir))
    downloads = work_dir / "downloads"
    source_roots = {}
    print(f"S2 adapter build scratch: {run_dir}", flush=True)
    total_started = time.monotonic()

    for name, source in lock["sources"].items():
        started = time.monotonic()
        archive = download_archive(name, source, downloads, args.offline,
                                   limits["max_archive_bytes"],
                                   limits["download_timeout_seconds"])
        destination = run_dir / "sources" / name
        extract = safe_extract_tar if source["archive_format"] == "tar.gz" else safe_extract_zip
        source_roots[name] = extract(archive, destination, source["top_level"],
                                     limits["max_extracted_bytes"],
                                     limits["max_archive_members"])
        print(f"  extracted {name} in {time.monotonic() - started:.1f}s", flush=True)

    build_root = run_dir / "build"
    s2_build = build_root / "s2"
    install_prefix = run_dir / "install"
    cmake_args = [
        "cmake", "-S", str(source_roots["s2geometry"]), "-B", str(s2_build),
        f"-DCMAKE_BUILD_TYPE={lock['build']['build_type']}",
        f"-DCMAKE_INSTALL_PREFIX={install_prefix}",
        f"-DCMAKE_CXX_STANDARD={lock['build']['cxx_standard']}",
        "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_TESTS=OFF", "-DBUILD_EXAMPLES=OFF",
        "-DFETCH_ABSEIL=ON",
        f"-DFETCHCONTENT_SOURCE_DIR_ABSL={source_roots['abseil_cpp']}",
        "-DFETCHCONTENT_FULLY_DISCONNECTED=ON", "-DFETCHCONTENT_UPDATES_DISCONNECTED=ON",
        "-DS2_ENABLE_INSTALL=ON", "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
    ]
    if sys.platform == "darwin":
        cmake_args.append(f"-DCMAKE_OSX_ARCHITECTURES={platform.machine()}")
        cmake_args.append(
            f"-DCMAKE_OSX_DEPLOYMENT_TARGET={lock['build']['macos_deployment_target']}"
        )

    timeout = limits["build_step_timeout_seconds"]
    run_step("S2 CMake configure", cmake_args, ROOT, run_dir / "s2-configure.log", timeout)
    run_step("S2 static build", ["cmake", "--build", str(s2_build),
                                  "--parallel", str(args.jobs)], ROOT,
             run_dir / "s2-build.log", timeout)
    run_step("S2 and Abseil local install", ["cmake", "--install", str(s2_build)], ROOT,
             run_dir / "s2-install.log", timeout)
    if not (install_prefix / "lib/libs2.a").is_file():
        raise RuntimeError("Pinned S2 build did not install lib/libs2.a")
    for header in ("s2boolean_operation.h", "s2memory_tracker.h"):
        if not (install_prefix / "include/s2" / header).is_file():
            raise RuntimeError(f"Pinned S2 header was not installed: {header}")

    adapter_build = build_root / "adapter"
    staged_library_dir = run_dir / "adapter-output"
    staged_library_dir.mkdir(mode=0o700)
    adapter_cmake = [
        "cmake", "-S", str(native_dir), "-B", str(adapter_build),
        f"-DCMAKE_BUILD_TYPE={lock['build']['build_type']}",
        f"-DCMAKE_CXX_STANDARD={lock['build']['cxx_standard']}",
        f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={staged_library_dir}",
        f"-DCMAKE_RUNTIME_OUTPUT_DIRECTORY={staged_library_dir}",
        f"-Ds2_DIR={install_prefix / 'share/s2'}",
        f"-Dabsl_DIR={install_prefix / 'lib/cmake/absl'}",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
    ]
    if sys.platform == "darwin":
        adapter_cmake.append(f"-DCMAKE_OSX_ARCHITECTURES={platform.machine()}")
        adapter_cmake.append(
            f"-DCMAKE_OSX_DEPLOYMENT_TARGET={lock['build']['macos_deployment_target']}"
        )
    run_step("adapter CMake configure", adapter_cmake, ROOT,
             run_dir / "adapter-configure.log", timeout)
    run_step("native S2 adapter build", ["cmake", "--build", str(adapter_build),
                                          "--target", lock["build"]["adapter_target"],
                                          "--parallel", str(args.jobs)], ROOT,
             run_dir / "adapter-build.log", timeout)

    staged_library = staged_library_dir / library_name
    if not staged_library.is_file() or staged_library.is_symlink() or not staged_library.stat().st_size:
        raise RuntimeError(f"Adapter did not produce expected library: {staged_library}")
    if (adapter_sources(ROOT, LOCK_PATH, BUILD_SCRIPT, BUILD_HELPERS) != sources
            or source_hashes(ROOT, sources) != source_snapshot):
        raise RuntimeError("Adapter sources changed during build; refusing to publish manifest")
    manifest = publish_artifact(output_dir, staged_library, library_name, lock_sha,
                                source_snapshot, lock["build"]["abi_version"],
                                sys.platform, platform.machine(), {
                                    "s2geometry-LICENSE": source_roots["s2geometry"] / "LICENSE",
                                    "s2geometry-NOTICE": source_roots["s2geometry"] / "NOTICE",
                                    "abseil_cpp-LICENSE": source_roots["abseil_cpp"] / "LICENSE",
                                })
    print(f"Published {output_dir / library_name}", flush=True)
    print(f"Build completed in {time.monotonic() - total_started:.1f}s", flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path,
                        help="explicit scratch directory for archives, build state, and logs")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="new, unused directory for the library and manifest")
    parser.add_argument("--jobs", type=int, default=4,
                        help="parallel compile jobs (maximum is 4)")
    parser.add_argument("--offline", action="store_true",
                        help="require hash-verified archives in --work-dir/downloads")
    print(json.dumps(build(parser.parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile,
            tarfile.TarError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
