"""Runtime integrity gates startup, while teardown stays available for recovery."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from gee.native import toolchains


def installed(tmp_path):
    profile = tmp_path/'engine/native-toolchains.json'
    profile.parent.mkdir()
    artifacts = []
    records = {}
    for kind, file in [('node', 'bin/node'), ('java', 'bin/java')]:
        home = tmp_path/'.native/toolchains'/kind
        binary = home/file; binary.parent.mkdir(parents=True); binary.write_bytes(b'synthetic runtime')
        artifacts.append(dict(kind=kind, directory=kind, sha256='1'*64))
        records[kind] = dict(archive_sha256='1'*64, critical_files={file:toolchains.digest(binary)})
    profile.write_text(json.dumps(dict(artifacts=artifacts)))
    lock = tmp_path/'.native/toolchain-lock.json'
    lock.write_text(json.dumps(dict(profile_sha256=toolchains.digest(profile), artifacts=records)))
    return profile


def test_modified_runtime_and_changed_profile_fail_closed(tmp_path):
    profile = installed(tmp_path)
    assert toolchains.selected(tmp_path)['node'].endswith('/node/bin/node')
    binary = tmp_path/'.native/toolchains/node/bin/node'
    binary.write_bytes(b'modified runtime')
    with pytest.raises(RuntimeError, match='integrity'): toolchains.selected(tmp_path)
    binary.write_bytes(b'synthetic runtime')
    profile.write_text(profile.read_text()+'\n')
    with pytest.raises(RuntimeError, match='profile changed'): toolchains.selected(tmp_path)


def test_missing_toolchain_cannot_prevent_owned_task_and_database_teardown(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1]/'scripts/native.py'
    spec = importlib.util.spec_from_file_location('native_teardown_test', path)
    native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
    root = tmp_path/'deployment'; control = root/'.native/run/tasks'; control.mkdir(parents=True)
    (root/'.native/config.json').touch()  # Presence only; no credentials are read.
    pg = root/'.native/postgres'; pg.mkdir(); (pg/'PG_VERSION').write_text('17')
    (control/'synthetic.state.json').write_text('{}')
    calls = []
    task = SimpleNamespace(status='running', stop=lambda **_: calls.append('task') or True)
    from gee.native import runtime
    monkeypatch.setattr(runtime, 'NativeClient', lambda: SimpleNamespace(control=control, get=lambda _: task))
    monkeypatch.setattr(native, 'ROOT', root); monkeypatch.setattr(native, 'NATIVE', root/'.native')
    monkeypatch.setattr(native, 'environment', lambda: (_ for _ in ()).throw(AssertionError('runtime gate during teardown')))
    monkeypatch.setattr(native, 'stop_service', lambda name: calls.append(name))
    monkeypatch.setattr(native.subprocess, 'run', lambda *a, **k: calls.append('database'))
    native.stop()
    assert calls == ['api','worker','task','database']
