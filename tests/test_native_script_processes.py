"""Kernel process denial and the durable launch gate use bounded probes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from gee.native.sandbox import profile,runtime_reads

ROOT=Path(__file__).resolve().parents[1]


def test_launch_gate_requires_explicit_supervisor_release(tmp_path):
    for release in [False,True]:
        marker=tmp_path/str(release)
        read,write=os.pipe()
        process=subprocess.Popen([sys.executable,'-m','gee.native.gate',str(read),
                                  sys.executable,'-c','from pathlib import Path;Path('+repr(str(marker))+').touch()'],
                                 cwd=ROOT,pass_fds=(read,),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        os.close(read)
        try:
            assert not marker.exists()
            if release:os.write(write,b'1')
        finally:os.close(write)
        _,stderr=process.communicate(timeout=5)
        assert process.returncode==(0 if release else 1),stderr.decode()
        assert marker.exists()==release


@pytest.mark.skipif(sys.platform!='darwin',reason='macOS Seatbelt acceptance')
def test_kernel_blocks_fork_detachment_and_posix_spawn(tmp_path):
    probe='''import os,json,errno
result={}
try:
 pid=os.fork()
 if pid==0:
  try:os.setsid();os._exit(0)
  except BaseException:os._exit(2)
 _,status=os.waitpid(pid,0)
 result['fork_detach']=os.waitstatus_to_exitcode(status)==0
except PermissionError:result['fork_detach']=False
try:
 pid=os.posix_spawn('/usr/bin/true',['true'],{})
 os.waitpid(pid,0);result['spawn']=True
except PermissionError:result['spawn']=False
print(json.dumps(result))'''
    for allowed in [True,False]:
        policy=profile(reads=runtime_reads(ROOT,sys.executable),writes=[tmp_path],fork=allowed)
        result=subprocess.run(['/usr/bin/sandbox-exec','-p',policy,sys.executable,'-c',probe],
                              cwd=tmp_path,env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=8)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)=={'fork_detach':allowed,'spawn':allowed}
