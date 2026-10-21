"""Native process backend for the durable scheduler; private state stays outside jobs."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import psutil
from .sandbox import profile, runtime_reads


class NotFound(Exception):
    pass


class NativeTask:
    def __init__(self, client, jid):
        self.client = client
        self.jid = jid
        self.base = client.control / jid
        if not self.base.with_suffix('.json').is_file():
            raise NotFound(jid)
        self.config = json.loads(self.base.with_suffix('.json').read_text())
        self.reload()

    def reload(self):
        path = self.base.with_suffix('.state.json')
        self.state = json.loads(path.read_text()) if path.exists() else {'status':'starting'}
        if self.state['status'] in {'starting','running'} and 'pid' in self.state:
            try:
                p = psutil.Process(self.state['pid'])
                if abs(p.create_time() - self.state['create_time']) > 0.01 or not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    raise psutil.NoSuchProcess(p.pid)
            except psutil.Error:
                child_pid=self.state.get('child_pid')
                if child_pid:
                    try:
                        child=psutil.Process(child_pid)
                        if abs(child.create_time()-self.state.get('child_create_time',0))<0.01 and os.getpgid(child_pid)==child_pid:
                            os.killpg(child_pid,signal.SIGKILL)
                    except (psutil.Error,ProcessLookupError):pass
                self.state.update(status='exited',exit_code=1,reason='supervisor_lost')
        self.status = self.state['status']
        self.attrs = {'State': {'ExitCode': self.state.get('exit_code',1),
                                'OOMKilled': self.state.get('reason') == 'memory_limit'},
                      'Config': {'Env': ['OPENEO_TOKEN='+self.config['env']['OPENEO_TOKEN']] if self.config['env'].get('OPENEO_TOKEN') else []}}

    def logs(self, tail=2000):
        path = self.base.with_suffix('.log')
        return path.read_bytes()[-200000:] if path.exists() else b''

    def stop(self, timeout=3):
        self.reload()
        if self.status not in {'running','starting'}:
            return
        pid = self.state.get('pid')
        if not pid:
            raise RuntimeError('Native supervisor did not publish its identity')
        p = psutil.Process(pid)
        if abs(p.create_time()-self.state['create_time']) > 0.01:
            raise RuntimeError('Process identity changed; refusing to signal')
        p.send_signal(signal.SIGTERM)
        deadline = time.monotonic()+timeout+2
        while time.monotonic() < deadline:
            self.reload()
            if self.status == 'exited':
                return
            time.sleep(0.1)
        raise RuntimeError('Native task failed to stop')

    def remove(self):
        self.reload()
        if self.status in {'running','starting'}:
            raise RuntimeError('Cannot release a running native task')
        self.base.with_suffix('.json').unlink(missing_ok=True)


class NativeClient:
    def __init__(self):
        self.root = Path(os.environ['GEE_PROJECT_ROOT']).resolve()
        self.control = self.root/'.native/run/tasks'
        self.control.mkdir(parents=True,exist_ok=True,mode=0o700)

    def get(self, name):
        return NativeTask(self,name.removeprefix('gee-'))

    def launch(self,row,folder=None):
        from .. import auth
        root = self.root
        jid = str(row['id'])
        folder = Path(folder) if folder is not None else Path(os.environ['DATA_ROOT'])/'jobs'/jid
        scratch = folder/'tmp'
        scratch.mkdir(mode=0o700,exist_ok=True)
        javascript = row.get('language') == 'javascript'
        python = str(root/'.venv/bin/python')
        node = os.environ['GEE_NODE']
        batch = row['kind'] == 'batch'
        env = {k:os.environ[k] for k in ['JAVA_HOME'] if k in os.environ}
        env.update(PATH='/usr/bin:/bin',HOME=str(scratch),TMPDIR=str(scratch),
                   PYTHONUNBUFFERED='1',PYTHONDONTWRITEBYTECODE='1',
                   PYTHONPATH=str(root),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
                   PROJ_NETWORK='OFF',GDAL_PAM_ENABLED='NO',GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR')
        reads = runtime_reads(root,python,node,engine=batch)
        reads.append(folder)
        writes = [scratch]
        port = None
        if batch:
            python = str(root/'.native/engine/bin/python')
            reads += [Path(os.environ['DATA_ROOT'])/'assets']
            writes = [folder]
            env.update(SPARK_LOCAL_IP='127.0.0.1',SPARK_LOCAL_HOSTNAME='localhost',
                       PATH='/opt/homebrew/opt/gdal/bin:/usr/bin:/bin',
                       PYSPARK_PYTHON=python,SPARK_HOME=str(root/'.native/engine/lib/python3.11/site-packages/pyspark'),
                       GEOPYSPARK_JARS_PATH=str(root/'.native/jars'),OPENEO_BACKEND_CONFIG=str(root/'engine/config.py'),
                       OPENEO_LOCAL_DEBUGGING='false',OPENEO_OTEL_ENABLED='false',OTEL_SDK_DISABLED='true',
                       OTEL_TRACES_EXPORTER='none',OTEL_METRICS_EXPORTER='none',OTEL_LOGS_EXPORTER='none',
                       AWS_EC2_METADATA_DISABLED='true',PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION='python')
            command = [python,str(root/'engine/native_run.py'),str(folder)]
        elif row['kind'] == 'ingest':
            from ..services.dataset_files import file_path
            source = file_path(row['context']['upload_id'])
            reads += [source]
            writes += [folder/'out']
            command = [python,str(root/'gee/raster_ingest_runner.py'),str(source),str(folder)]
        else:
            token = auth.issue(row['user_id'],scope='script',hours=1,job_id=jid)
            port = int(os.environ.get('GEE_PORT','8787'))
            env.update(OPENEO_URL=f'http://127.0.0.1:{port}/openeo/1.2',OPENEO_TOKEN=token,
                       GEE_SCRIPT_PATH=str(folder/'script.py'))
            command = [node,str(root/'.native/eejs/runner.cjs'),str(folder/'script.js')] if javascript else [python,str(root/'gee/script_runner.py')]
        sandbox = self.control/(jid+'.sb')
        sandbox.write_text(profile(reads=reads,writes=writes,api_port=port,spark=batch))
        sandbox.chmod(0o600)
        config = {'command':['/usr/bin/sandbox-exec','-f',str(sandbox),*command],
                  'cwd':str(scratch),'env':env,'timeout':1800 if batch else (180 if row['kind']=='ingest' else 120),
                  'memory_bytes':(4096 if batch else (2048 if row['kind']=='ingest' else 512))*1024**2,
                  'state':str(self.control/(jid+'.state.json')),'log':str(self.control/(jid+'.log'))}
        manifest = self.control/(jid+'.json')
        manifest.write_text(json.dumps(config));manifest.chmod(0o600)
        manager_env = {'PATH':'/usr/bin:/bin','PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1'}
        with (self.control/(jid+'.supervisor.log')).open('ab') as log:
            subprocess.Popen([str(root/'.venv/bin/python'),'-m','gee.native.task',str(manifest)],
                             env=manager_env,cwd=root,start_new_session=True,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        return NativeTask(self,jid)
