"""The real synchronous bridge uses one process and a bounded worker thread."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def server():
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def do_POST(self):
            assert self.path=='/gee/v1/dispatch'
            assert self.headers['Authorization']=='Bearer basic//synthetic-token'
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(payload)
            action=payload['action']
            value=({'pending':True,'job_id':'synthetic-child','warnings':['合成提示']}
                   if action=='evaluate' else {'value':{'text':'影像🌍','state':'READY'}})
            status=400 if action=='error' else 200
            if action=='error': value={'message':'synthetic failure'}
            if action=='large': value={'value':'x'*1048576}
            data=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try: yield http.server_address[1], calls
    finally: http.shutdown();http.server_close();thread.join(timeout=3)


def bridge(code,port,*,sandbox=False,tmp_path=None):
    node=shutil.which('node')
    if not node: pytest.skip('Node required')
    source="const {send}=require("+json.dumps(str(ROOT/'runtimes/eejs/bridge.cjs'))+");\n"+code
    args=[node,'-e',source]
    env={'PATH':'/usr/bin:/bin','OPENEO_URL':f'http://127.0.0.1:{port}/openeo/1.2','OPENEO_TOKEN':'synthetic-token'}
    if sandbox:
        from gee.native.sandbox import profile,runtime_reads
        policy=profile(reads=[*runtime_reads(ROOT,sys.executable,node),ROOT/'runtimes/eejs'],
                       writes=[tmp_path],api_port=port,fork=False)
        args=['/usr/bin/sandbox-exec','-p',policy,*args]
        env.update(HOME=str(tmp_path),TMPDIR=str(tmp_path))
    return subprocess.run(args,env=env,cwd=tmp_path if sandbox else ROOT,capture_output=True,text=True,timeout=20)


def test_real_bridge_synchronous_polling_unicode_and_errors(server):
    port,calls=server
    result=bridge("console.log(JSON.stringify(send({action:'evaluate'})));try{send({action:'error'})}catch(e){console.log(e.message)}",port)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout.splitlines()[0])
    assert value=={'value':{'text':'影像🌍','state':'READY'},'warnings':['合成提示']}
    assert 'synthetic failure' in result.stdout
    assert [x['action'] for x in calls]==['evaluate','result','error']


def test_bridge_request_and_response_byte_limits(server):
    port,calls=server
    result=bridge("for(const p of [{action:'large'},{action:'never',text:'🌍'.repeat(300000)}]){try{send(p);throw Error('unexpected success')}catch(e){console.log(e.message)}}",port)
    assert result.returncode==0,result.stderr
    assert 'response exceeds 1 MiB' in result.stdout and 'request exceeds 1 MiB' in result.stdout
    assert [x['action'] for x in calls]==['large']


@pytest.mark.skipif(os.sys.platform!='darwin',reason='macOS Seatbelt acceptance')
def test_real_bridge_works_while_subprocess_creation_is_denied(server,tmp_path):
    port,_=server
    code="""const cp=require('node:child_process');
const result=cp.spawnSync('/usr/bin/true');
if(!result.error || result.error.code!=='EPERM')throw Error('subprocess escaped');
console.log(JSON.stringify(send({action:'status'})));"""
    result=bridge(code,port,sandbox=True,tmp_path=tmp_path)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['value']['state']=='READY'
