"""Real fixed-volume cleanup after completion, cancel, timeout and supervisor loss."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

import psutil
import pytest
from gee.native import scratch
from gee.native.sandbox import profile,runtime_reads

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(sys.platform!='darwin',reason='macOS native lifecycle acceptance')


@pytest.mark.parametrize('mode',['normal','error','timeout','cancel','supervisor_loss'])
def test_terminated_script_releases_bounded_storage(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(scratch,'CAPACITY_MIB',32)
    project=tmp_path/'project';project.mkdir()
    jid=str(uuid4());folder=project/'data/jobs'/jid;own=folder/'tmp';own.mkdir(parents=True)
    lease=scratch.reserve(project,jid,own)
    state=tmp_path/'state.json';log=tmp_path/'log';manifest=tmp_path/'manifest.json'
    code="from pathlib import Path;Path('ordinary').write_text('allowed');print('LEGITIMATE',flush=True);"
    code+=('raise ValueError("synthetic script error")' if mode=='error' else
           'import time;time.sleep(60)' if mode not in {'normal'} else '')
    policy=profile(reads=runtime_reads(ROOT,sys.executable),writes=[own],fork=False)
    config=dict(command=['/usr/bin/sandbox-exec','-p',policy,sys.executable,'-u','-c',code],
                cwd=str(own),env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(ROOT),'HOME':str(own),'TMPDIR':str(own)},
                timeout=1 if mode=='timeout' else 15,memory_bytes=256*1024**2,
                state=str(state),log=str(log),scratch_lease=str(lease))
    manifest.write_text(json.dumps(config))
    # The smaller fixture capacity stays confined to this trusted test supervisor.
    launcher='from gee.native import scratch,task;scratch.CAPACITY_MIB=32;task.main('+repr(str(manifest))+')'
    process=subprocess.Popen([sys.executable,'-c',launcher],cwd=ROOT,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    child=None
    try:
        if mode in {'cancel','supervisor_loss'}:
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if state.exists():
                    value=json.loads(state.read_text())
                    if value.get('child_pid') and log.exists() and 'LEGITIMATE' in log.read_text():
                        child={'pid':value['child_pid'],'created':value['child_create_time']};break
                time.sleep(.05)
            assert child,'supervisor did not release a running script'
            process.send_signal(signal.SIGTERM if mode=='cancel' else signal.SIGKILL)
        _,stderr=process.communicate(timeout=20)
        if mode=='supervisor_loss':
            scratch.recover(project)
            assert not scratch.alive(child)
        else:
            result=json.loads(state.read_text())
            assert result['status']=='exited',stderr.decode()
            assert result['reason']==({'timeout':'timeout','cancel':'stopped'}.get(mode))
            assert (result['exit_code']==0)==(mode=='normal')
            assert 'LEGITIMATE' in log.read_text()
        assert not lease.exists() and not os.path.ismount(own)
    finally:
        if process.poll() is None:
            process.kill();process.communicate(timeout=5)
        if child and scratch.alive(child):
            os.killpg(child['pid'],signal.SIGKILL)
            try:psutil.Process(child['pid']).wait(timeout=5)
            except psutil.NoSuchProcess:pass
        if lease.exists():scratch.release(lease,recovering=True)
