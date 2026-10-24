"""The adapter builder must import as a package and run as a direct script."""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_builder_package_import_works_without_adding_scripts_to_sys_path():
    result = subprocess.run(
        [sys.executable, "-c", "from scripts.build_integer_adapter import SOURCES; print(len(SOURCES))"],
        cwd=ROOT, text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) >= 3


def test_builder_direct_script_help_does_not_read_deployment_config():
    result = subprocess.run(
        [sys.executable, "scripts/build_integer_adapter.py", "--help"],
        cwd=ROOT, text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--standalone" in result.stdout and "--java-home" in result.stdout
