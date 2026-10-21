"""Resource limits, cancellation and recovery against real running containers."""
import json,secrets,subprocess,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];BASE='http://localhost:8787';records=[]
password=secrets.token_urlsafe(20)
subprocess.run(['docker-compose','exec','-T','api','python','-c','from gee import auth;auth.create_user("audit_runtime",'+repr(password)+')'],cwd=ROOT,check=True)
s=requests.Session();s.headers['Origin']=BASE;s.post(BASE+'/workbench/login',json={'username':'audit_runtime','password':password}).raise_for_status()
def api(path,method='get',body=None):
 r=getattr(s,method)(BASE+path,json=body,timeout=20);r.raise_for_status();return r.json()
def submit(title,code):return api('/workbench/jobs','post',{'title':title,'code':code})['id']
def state(j):return api('/workbench/jobs/'+j+'/logs')
def until(j,predicate,timeout=180):
 end=time.time()+timeout
 while time.time()<end:
  r=state(j)
  if predicate(r):return r
  time.sleep(1)
 raise RuntimeError('Acceptance timed out '+j)
def check(name,condition,detail):
 records.append({'test':name,'passed':bool(condition),'detail':detail});print(records[-1],flush=True)
# A running job must retain its exact container through API/scheduler restart.
j=submit('恢复验收','import time\nprint("RECOVERY_START",flush=True)\ntime.sleep(35)\nprint("RECOVERY_DONE",flush=True)')
until(j,lambda r:r['status']=='running')
before=subprocess.check_output(['docker','inspect','gee-'+j,'--format','{{.Id}}'],text=True).strip()
subprocess.run(['docker-compose','restart','api','worker'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
for _ in range(30):
 try:
  api('/workbench/me');break
 except requests.RequestException:time.sleep(1)
after=subprocess.check_output(['docker','inspect','gee-'+j,'--format','{{.Id}}'],text=True).strip()
r=until(j,lambda r:r['status'] in {'error','finished'})
check('running container survives API/scheduler restart',before==after and r['status']=='finished' and 'RECOVERY_DONE' in r['logs'],{'job':j,'container_unchanged':before==after,'status':r['status']})
# Launch timeout in parallel with short checks so full configured limit is exercised.
t=submit('超时验收','import time\ntime.sleep(180)')
m=submit('内存上限验收','blocks=[]\nwhile True:\n blocks.append(bytearray(32*1024*1024))')
r=until(m,lambda r:r['status'] in {'error','finished'})
check('512 MiB memory limit',r['status']=='error' and r['error']=='内存超限',r)
j=submit('运行中取消验收','import time\nprint("CANCEL_START",flush=True)\ntime.sleep(90)')
until(j,lambda r:r['status']=='running');api('/workbench/jobs/'+j+'/cancel','post',{})
until(j,lambda r:r['status']=='canceled')
for _ in range(15):
 q=subprocess.run(['docker','inspect','gee-'+j],capture_output=True)
 if q.returncode:break
 time.sleep(1)
check('running cancellation removes execution container',q.returncode!=0,{'job':j,'status':state(j)['status']})
j=submit('DNS 隔离验收','import socket\ntry:\n socket.getaddrinfo("example.com",443)\n print("DNS_LEAK")\nexcept OSError:\n print("DNS_BLOCKED")')
r=until(j,lambda r:r['status'] in {'finished','error'});check('public DNS blocked','DNS_BLOCKED' in r['logs'] and 'DNS_LEAK' not in r['logs'],r)
r=until(t,lambda r:r['status'] in {'error','finished'})
check('120 second script timeout',r['status']=='error' and r['error']=='执行超时',r)
(ROOT/'audit/runtime-integration.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));assert all(x['passed'] for x in records)
