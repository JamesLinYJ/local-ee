"""The pinned spherical adapter works inside the existing deny-default profile."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from gee.native.sandbox import profile, runtime_reads


ROOT = Path(__file__).resolve().parents[1]


def test_only_trusted_runtime_modes_request_spherical_read_paths(tmp_path, monkeypatch):
    public_paths = [tmp_path / 'native/s2', tmp_path / 'scripts/s2_build']
    for path in public_paths:
        path.mkdir(parents=True)
    builder = tmp_path / 'scripts/build_s2_adapter.py'
    builder.write_text('# synthetic public source\n')
    public_paths.append(builder)
    monkeypatch.setenv('JAVA_HOME', str(tmp_path / 'jdk'))
    assert not set(public_paths) & set(runtime_reads(tmp_path, sys.executable))
    for options in ({'spherical': True}, {'engine': True}):
        assert set(public_paths) <= set(runtime_reads(tmp_path, sys.executable, **options))


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS Seatbelt component acceptance')
def test_actual_spherical_compilation_keeps_file_write_and_network_denials(tmp_path):
    own = tmp_path / 'own'
    own.mkdir()
    foreign = tmp_path / 'foreign'
    foreign.write_text('synthetic private file')
    write_probe = ROOT / 'native/s2/artifacts' / ('seatbelt-probe-' + uuid.uuid4().hex)
    reads = runtime_reads(ROOT, sys.executable, spherical=True)
    rules = profile(reads=reads, writes=[own], package_roots=[ROOT], fork=False)
    code = f'''
import json, pathlib, socket, sys
sys.path.insert(0, {str(ROOT)!r})
from gee.ee_translate import compile_expression
expression = {{'type': 'Invocation', 'functionName': 'Geometry.contains',
 'arguments': {{'left': {{'type': 'Polygon', 'coordinates': [[
  [170,-10],[-170,-10],[-170,10],[170,10],[170,-10]]]}},
  'right': {{'type': 'Point', 'coordinates': [179,0]}}}}}}
assert compile_expression(expression, [], {{}})['value'] is True
observations = {{'spherical_dateline_computation': True}}
try:
 pathlib.Path({str(foreign)!r}).read_bytes()
except PermissionError:
 observations['foreign_file_denied'] = True
try:
 pathlib.Path({str(write_probe)!r}).write_text('must be denied')
except PermissionError:
 observations['artifact_write_denied'] = True
try:
 socket.create_connection(('198.51.100.1', 443), timeout=1)
except PermissionError:
 observations['public_network_denied'] = True
print(json.dumps(observations))
'''
    try:
        result = subprocess.run(
            ['/usr/bin/sandbox-exec', '-p', rules, sys.executable, '-c', code],
            cwd=own, env={'PATH': '/usr/bin:/bin', 'HOME': str(own), 'TMPDIR': str(own),
                          'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1'},
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            'spherical_dateline_computation': True, 'foreign_file_denied': True,
            'artifact_write_denied': True, 'public_network_denied': True,
        }
        assert not write_probe.exists()
    finally:
        write_probe.unlink(missing_ok=True)
