"""Real kernel boundary and supervisor checks, not mocked process isolation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import pytest
from gee.native.sandbox import profile,runtime_reads

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(sys.platform!='darwin',reason='macOS Seatbelt acceptance')


def command(tmp_path,code,*,node=False,port=None):
    own=tmp_path/'own';own.mkdir(exist_ok=True)
    reads=runtime_reads(ROOT,sys.executable,shutil.which('node') if node else None)
    policy=profile(reads=reads,writes=[own],api_port=port)
    executable=shutil.which('node') if node else sys.executable
    args=[executable,'-e' if node else '-c',code]
    return subprocess.run(['/usr/bin/sandbox-exec','-p',policy,*args],cwd=own,
                          env={'PATH':'/usr/bin:/bin','HOME':str(own),'TMPDIR':str(own),'PYTHONDONTWRITEBYTECODE':'1'},
                          capture_output=True,text=True,timeout=15)


def test_python_denies_foreign_files_symlinks_writes_and_network(tmp_path):
    secret=tmp_path/'credential';secret.write_text('must not escape')
    deployment=tmp_path/'deployment';deployment.mkdir()
    config=deployment/'config.json';config.write_text('{"credential":"synthetic-test-only"}')
    (tmp_path/'own').mkdir();(tmp_path/'own/link').symlink_to(secret)
    code=f'''import pathlib,socket,json
r={{}}
for key,path in [('credential',{str(secret)!r}),('symlink','link'),('deployment',{str(config)!r})]:
 try:pathlib.Path(path).read_bytes();r[key]=False
 except PermissionError:r[key]=True
try:pathlib.Path({str(tmp_path/'outside-write')!r}).write_text('forbidden');r['foreign_write']=False
except PermissionError:r['foreign_write']=True
for key,host in [('public','198.51.100.1'),('other_local_service','127.0.0.1')]:
 try:socket.create_connection((host,443),timeout=1);r[key]=False
 except PermissionError:r[key]=True
pathlib.Path('own.txt').write_text('allowed');r['own_write']=True
print(json.dumps(r))'''
    result=command(tmp_path,code)
    assert result.returncode==0,result.stderr
    values=json.loads(result.stdout)
    assert len(values)==7 and all(values.values()),values
    assert not (tmp_path/'outside-write').exists()


def test_node_cannot_read_host_credentials(tmp_path):
    deployment=tmp_path/'deployment';deployment.mkdir()
    config=deployment/'config.json';config.write_text('{"credential":"synthetic-test-only"}')
    code=f'''const fs=require('node:fs');
try{{fs.readFileSync({json.dumps(str(config))});process.exit(2)}}
catch(e){{if(e.code!=='EPERM' && e.code!=='EACCES')throw e;console.log('DENIED')}}'''
    result=command(tmp_path,code,node=True)
    assert result.returncode==0 and 'DENIED' in result.stdout,result.stderr


def test_python_package_directory_listing_does_not_grant_child_file_reads(tmp_path):
    deployment=tmp_path/'deployment';package=deployment/'audited_package';package.mkdir(parents=True)
    (package/'__init__.py').write_text('value=7')
    secret=deployment/'private-config';secret.write_text('synthetic credential')
    own=tmp_path/'own';own.mkdir()
    rules=profile(reads=[*runtime_reads(ROOT,sys.executable),package],writes=[own],
                  package_roots=[deployment],fork=False)
    code=f'''import sys,pathlib
sys.path.insert(0,{str(deployment)!r})
import audited_package
assert audited_package.value==7
try:pathlib.Path({str(secret)!r}).read_bytes();raise RuntimeError('CHILD FILE EXPOSED')
except PermissionError:print('IMPORT_ALLOWED_SECRET_DENIED')
'''
    result=subprocess.run(['/usr/bin/sandbox-exec','-p',rules,sys.executable,'-c',code],
                          cwd=own,capture_output=True,text=True,timeout=15,
                          env={'PATH':'/usr/bin:/bin','HOME':str(own),'TMPDIR':str(own),'PYTHONDONTWRITEBYTECODE':'1'})
    assert result.returncode==0 and 'IMPORT_ALLOWED_SECRET_DENIED' in result.stdout,result.stderr


def test_only_declared_api_port_is_allowed(tmp_path):
    from http.server import BaseHTTPRequestHandler,HTTPServer
    import threading
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(b'LOCAL_API_OK')
        def log_message(self,*_):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    port=server.server_address[1]
    try:
        code=f"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:{port}',timeout=2).read().decode())"
        result=command(tmp_path,code,port=port)
        assert result.returncode==0 and 'LOCAL_API_OK' in result.stdout,result.stderr
        result=command(tmp_path,code)
        assert result.returncode!=0 and 'Operation not permitted' in result.stderr
    finally:
        server.shutdown();server.server_close()


def test_supervisor_enforces_timeout_redacts_token_and_survives_reader_restart(tmp_path):
    own=tmp_path/'own';own.mkdir()
    policy=tmp_path/'task.sb';policy.write_text(profile(reads=runtime_reads(ROOT,sys.executable),writes=[own]))
    state=tmp_path/'task.state.json';log=tmp_path/'task.log';manifest=tmp_path/'task.json'
    token='native-sandbox-test-token-not-a-real-credential'
    config={'command':['/usr/bin/sandbox-exec','-f',str(policy),sys.executable,'-u','-c',
                       'import os,time;print(os.environ["OPENEO_TOKEN"]);time.sleep(60)'],
            'cwd':str(own),'env':{'PATH':'/usr/bin:/bin','HOME':str(own),'TMPDIR':str(own),'OPENEO_TOKEN':token},
            'timeout':2,'memory_bytes':256*1024**2,'state':str(state),'log':str(log)}
    manifest.write_text(json.dumps(config))
    process=subprocess.Popen([sys.executable,'-m','gee.native.task',str(manifest)],cwd=ROOT,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdout,stderr=process.communicate(timeout=15)
    assert process.returncode==0,stderr.decode()
    result=json.loads(state.read_text())
    assert result['status']=='exited' and result['reason']=='timeout'
    assert token not in log.read_text() and '[REDACTED]' in log.read_text()
    assert 'OPENEO_TOKEN' not in json.loads(manifest.read_text())['env']
    # State is reconstructible without the scheduling process or its Popen object.
    from gee.native.runtime import NativeTask
    from types import SimpleNamespace
    task=NativeTask(SimpleNamespace(control=tmp_path),'task')
    assert task.status=='exited' and task.attrs['State']['ExitCode']!=0
    task.remove();assert not manifest.exists()
