#!/usr/bin/env python3
"""Explicit on-demand native services; no Docker, Colima, VM or login autostart."""
import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
NATIVE=ROOT/'.native'
RUN=NATIVE/'run'
PG=Path('/opt/homebrew/opt/postgresql@17/bin')


def execute(args,**kwargs):
    return subprocess.run([str(x) for x in args],check=True,cwd=ROOT,**kwargs)


def config():
    path=NATIVE/'config.json'
    if not path.exists():
        raise SystemExit('Run .venv/bin/python scripts/native.py init first')
    return json.loads(path.read_text())


def environment():
    c=config()
    from gee.native.toolchains import selected
    runtimes=selected(ROOT)
    env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_CTYPE'}}
    env.update(GEE_RUNTIME='native',GEE_PROJECT_ROOT=str(ROOT),DATA_ROOT=str(ROOT/'data'),
               UPLOAD_ROOT=str(ROOT/'data/uploads'),GEE_PORT=str(c['port']),
               PUBLIC_ORIGIN=f"http://localhost:{c['port']}",
               DATABASE_URL=f"postgresql://gee:{quote(c['database_password'],safe='')}@/gee?host={quote(str(RUN/'pg'),safe='')}&port=55432",
               PYTHONPATH=str(ROOT),PYTHONUNBUFFERED='1',PYTHONDONTWRITEBYTECODE='1',
               JAVA_HOME=runtimes['java_home'],GEE_NODE=runtimes['node'],OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
               OTEL_SDK_DISABLED='true',OPENEO_OTEL_ENABLED='false',PROJ_NETWORK='OFF')
    env['TZ']='UTC'
    return env


def initialize():
    os.umask(0o077)
    NATIVE.mkdir(exist_ok=True,mode=0o700);RUN.mkdir(exist_ok=True,mode=0o700)
    (RUN/'pg').mkdir(exist_ok=True,mode=0o700)
    for name in ['assets','catalog','jobs','raw','uploads']:(ROOT/'data'/name).mkdir(exist_ok=True,parents=True)
    path=NATIVE/'config.json'
    if not path.exists():
        from gee.native.toolchains import selected
        runtimes=selected(ROOT)
        path.write_text(json.dumps({'database_password':secrets.token_urlsafe(32),'port':8787,**runtimes},indent=2))
        path.chmod(0o600)
    if not (NATIVE/'postgres/PG_VERSION').exists():
        c=config();pw=RUN/'init-password'
        pw.write_text(c['database_password']);pw.chmod(0o600)
        try:execute([PG/'initdb','-D',NATIVE/'postgres','-U','gee','--auth=scram-sha-256','--encoding=UTF8','--locale=C','--pwfile',pw],stdout=subprocess.DEVNULL)
        finally:pw.unlink(missing_ok=True)
        with (NATIVE/'postgres/postgresql.conf').open('a') as out:
            out.write(f"\nlisten_addresses = ''\nport = 55432\nunix_socket_directories = '{RUN/'pg'}'\nunix_socket_permissions = 0700\nmax_connections = 20\nshared_buffers = 32MB\nwork_mem = 4MB\nmaintenance_work_mem = 32MB\n")
    ee=NATIVE/'eejs';ee.mkdir(exist_ok=True)
    for p in (ROOT/'runtimes/eejs').glob('*.cjs'):shutil.copy2(p,ee/p.name)
    shutil.copytree(ROOT/'vendor/earthengine-js',ee/'vendor',dirs_exist_ok=True)
    print('Native configuration initialized; secrets were not printed.')


def database():
    status=subprocess.run([str(PG/'pg_ctl'),'-D',str(NATIVE/'postgres'),'status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if status.returncode:
        execute([PG/'pg_ctl','-D',NATIVE/'postgres','-l',RUN/'postgres.log','-w','start'],stdout=subprocess.DEVNULL)
    env=environment();os.environ.update(env)
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    values=conninfo_to_dict(env['DATABASE_URL']);values['dbname']='postgres'
    with psycopg.connect(**values,autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname='gee'").fetchone():
            connection.execute('CREATE DATABASE gee')
    from gee.migrations import migrate
    from gee import db,auth
    migrate()
    if not db.query('SELECT id FROM users LIMIT 1'):
        password=secrets.token_urlsafe(20)
        auth.create_user('admin',password,role='admin')
        login=ROOT/'deploy/native-login.txt'
        login.write_text('URL: http://localhost:8787\nUsername: admin\nPassword: '+password+'\n')
        login.chmod(0o600)
        print('New local account created; credentials: deploy/native-login.txt')
    # Re-index retained local catalog files, never resurrect the deleted users/jobs DB.
    if not db.query('SELECT id FROM collections LIMIT 1'):
        from psycopg.types.json import Jsonb
        import hashlib
        count=0
        with db.connect() as connection:
            for directory in sorted((ROOT/'data/catalog').iterdir()):
                collection=directory/'collection.json'
                if not directory.is_dir() or directory.is_symlink() or not collection.is_file():continue
                meta=json.loads(collection.read_text());cid=meta['id']
                enabled=not cid.startswith('admin-acceptance-')
                connection.execute('INSERT INTO collections(id,metadata,enabled) VALUES(%s,%s,%s)',(cid,Jsonb(meta),enabled))
                for path in sorted(directory.glob('*.json')):
                    if path.name=='collection.json' or path.is_symlink():continue
                    item=json.loads(path.read_text())
                    active=not (cid=='sentinel-2-l2a' and item.get('properties',{}).get('gee:source_collection')!='sentinel-2-c1-l2a')
                    for asset in item.get('assets',{}).values():
                        href=asset.get('href','')
                        if not href.startswith('/data/assets/') or not (ROOT/'data'/href.removeprefix('/data/')).is_file():
                            active=False
                    connection.execute('INSERT INTO items(id,collection_id,metadata,checksum,active) VALUES(%s,%s,%s,%s,%s)',
                                       (item['id'],cid,Jsonb(item),hashlib.sha256(path.read_bytes()).hexdigest(),active))
                    count+=int(active)
        print('Retained local catalog indexed; active items:',count)


def process(name):
    path=RUN/(name+'.pid.json')
    if not path.is_file():return None
    record=json.loads(path.read_text())
    try:
        p=psutil.Process(record['pid'])
        return p if abs(p.create_time()-record['create_time'])<0.01 and p.status()!=psutil.STATUS_ZOMBIE else None
    except psutil.Error:return None


def start():
    initialize();database()
    if not (NATIVE/'engine-lock.json').is_file():
        raise SystemExit('Native engine is not built; run scripts/setup_native_engine.py first')
    env=environment()
    from gee.native.sandbox import profile,runtime_reads
    scratch=RUN/'api-tmp';scratch.mkdir(exist_ok=True,mode=0o700)
    rules=profile(reads=[*runtime_reads(ROOT,ROOT/'.venv/bin/python'),ROOT/'web/dist',ROOT/'examples',ROOT/'data',RUN/'pg'],
                  writes=[scratch,ROOT/'data/uploads'])
    rules+='(allow file-read* (literal '+json.dumps(str(ROOT))+'))\n'
    port=config()['port']
    rules+=f'(allow network-inbound network-bind (local tcp "localhost:{port}"))\n(allow network-outbound (remote unix-socket))\n'
    sandbox=RUN/'api.sb';sandbox.write_text(rules)
    commands={'api':[str(ROOT/'.venv/bin/python'),'-m','gunicorn','--bind',f"127.0.0.1:{config()['port']}",'--workers','1','--threads','4','--timeout','120','--no-control-socket','--no-sendfile','gee.app:create_app()'],
              'worker':[str(ROOT/'.venv/bin/python'),'-m','gee.worker']}
    for name,args in commands.items():
        if process(name):continue
        service_env=dict(env)
        if name=='api':
            args=['/usr/bin/sandbox-exec','-f',str(sandbox),*args]
            service_env.update(HOME=str(scratch),TMPDIR=str(scratch))
        with (RUN/(name+'.log')).open('ab') as log:
            p=subprocess.Popen(args,cwd=ROOT,env=service_env,start_new_session=True,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
        (RUN/(name+'.pid.json')).write_text(json.dumps({'pid':p.pid,'create_time':psutil.Process(p.pid).create_time()}))
    import urllib.request
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config()['port']}/openeo/1.2",timeout=1) as response:
                if response.status==200:break
        except OSError:time.sleep(0.3)
    else:raise RuntimeError('API did not become ready; see .native/run/api.log')
    print('Native workbench ready: http://localhost:'+str(config()['port']))


def stop_service(name):
    p=process(name)
    if p:
        p.send_signal(signal.SIGTERM)
        try:p.wait(timeout=8)
        except psutil.TimeoutExpired:
            if process(name):os.killpg(p.pid,signal.SIGKILL)
    (RUN/(name+'.pid.json')).unlink(missing_ok=True)


def stop():
    # Stop submission and scheduling first, then terminate only verified task supervisors.
    for name in ['api','worker']:stop_service(name)
    if (NATIVE/'config.json').exists():
        # Teardown needs only control paths, even if a runtime integrity check fails.
        os.environ['GEE_PROJECT_ROOT']=str(ROOT)
        from gee.native.runtime import NativeClient,NotFound
        client=NativeClient()
        for path in client.control.glob('*.state.json'):
            try:task=client.get('gee-'+path.name.removesuffix('.state.json'))
            except NotFound:continue
            if task.status in {'running','starting'}:
                deadline=time.monotonic()+210
                while task.stop(timeout=1) is False:
                    if time.monotonic()>deadline:
                        raise RuntimeError('Native task cleanup remains pending; controls and capacity retained')
    if (NATIVE/'postgres/PG_VERSION').exists():
        subprocess.run([str(PG/'pg_ctl'),'-D',str(NATIVE/'postgres'),'-w','-m','fast','stop'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print('Native services stopped. Data retained; no VM or container involved.')


def main():
    os.umask(0o077)
    if sys.platform!='darwin':raise SystemExit('This launcher requires macOS; no container fallback exists')
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['init','start','stop','status','env'])
    args=parser.parse_args()
    if args.command=='init':initialize();database()
    elif args.command=='start':start()
    elif args.command=='stop':stop()
    elif args.command=='status':
        print(json.dumps({'runtime':'native macOS','api':bool(process('api')),'worker':bool(process('worker')),'url':'http://localhost:8787'},indent=2))
    else:
        # Deliberately do not provide a secret-printing environment command.
        print('Use environment() from this module within a trusted process; secrets are never printed.')


if __name__=='__main__':main()
