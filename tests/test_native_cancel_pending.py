"""Slow filesystem cleanup must not stop the durable scheduler or launch canceled code."""
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from gee.native.runtime import NativeTask

ROOT = Path(__file__).resolve().parents[1]


def test_cancel_during_slow_prepare_remains_pending_then_exits(tmp_path):
    marker = tmp_path/'preparing'
    executed = tmp_path/'should-not-run'
    manifest = tmp_path/'task.json'
    manifest.write_text(json.dumps(dict(
        command=[sys.executable, '-c', f'from pathlib import Path;Path({str(executed)!r}).touch()'],
        cwd=str(tmp_path), env={'PATH': '/usr/bin:/bin'}, timeout=20,
        memory_bytes=256*1024**2, state=str(tmp_path/'task.state.json'),
        log=str(tmp_path/'task.log'), scratch_lease=str(tmp_path/'synthetic-lease'))))
    launcher = f'''from pathlib import Path
import time
from gee.native import scratch,task
def slow_prepare(_):
 Path({str(marker)!r}).touch()
 time.sleep(6.5)
scratch.prepare=slow_prepare
scratch.release=lambda *a,**k:None
task.main({str(manifest)!r})
'''
    process = subprocess.Popen([sys.executable, '-c', launcher], cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline: time.sleep(.02)
        assert marker.exists()
        task = NativeTask(SimpleNamespace(control=tmp_path), 'task')
        assert task.stop(timeout=3) is False
        _, stderr = process.communicate(timeout=10)
        task.reload()
        assert process.returncode == 0, stderr.decode()
        assert task.status == 'exited' and task.state['reason'] == 'stopped'
        assert not executed.exists()
    finally:
        if process.poll() is None:
            process.kill(); process.communicate(timeout=5)


def test_scheduler_defers_publication_and_admission_until_stop_finishes(monkeypatch):
    from gee import worker
    row = dict(id='synthetic', kind='script', status='canceled', started=None)
    queries = []
    def query(sql, *args, **kwargs):
        queries.append(sql)
        if "SELECT * FROM jobs WHERE status IN" in sql: return [row]
        raise AssertionError('Pending cancellation must not admit or finalize jobs')
    monkeypatch.setattr(worker.db, 'query', query)
    monkeypatch.setattr(worker, 'finish', lambda *_: (_ for _ in ()).throw(AssertionError('premature publication')))
    container = SimpleNamespace(stop=lambda **_: False, reload=lambda: None, status='starting')
    worker.tick(SimpleNamespace(get=lambda _: container))
    assert len(queries) == 1
