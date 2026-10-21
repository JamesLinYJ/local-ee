"""Integration checks against the real local Postgres/API/Docker runner. No fake engine."""
import concurrent.futures
import json
import secrets
import subprocess
import time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1];BASE='http://localhost:8787'
records=[]
def check(name,condition,detail=None):
    records.append({'test':name,'passed':bool(condition),'detail':detail});assert condition,(name,detail)
def account(name):
    password=secrets.token_urlsafe(20)
    code='from gee import auth;auth.create_user('+repr(name)+','+repr(password)+')'
    subprocess.run(['docker-compose','exec','-T','api','python','-c',code],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    s=requests.Session();s.headers['Origin']=BASE
    r=s.post(BASE+'/workbench/login',json={'username':name,'password':password});r.raise_for_status()
    return s,password
def request(s,path,method='get',body=None):return getattr(s,method)(BASE+path,json=body,timeout=20)
def wait(s,jid,seconds=45):
    until=time.time()+seconds
    while time.time()<until:
        r=request(s,f'/workbench/jobs/{jid}/logs').json()
        if r['status'] in {'finished','error','canceled'}:return r
        time.sleep(1)
    raise RuntimeError('job timeout in acceptance harness')
try:
    a,ap=account('audit_alice');b,bp=account('audit_bob')
    sid=request(a,'/workbench/scripts','post',{'title':'private-check','code':'print(1)','shared':False}).json()['id']
    check('private script hidden',sid not in [s['id'] for s in request(b,'/workbench/scripts').json()])
    check('foreign script edit denied',request(b,'/workbench/scripts/'+sid,'put',{'code':'print(2)'}).status_code==404)
    check('explicit share',request(a,'/workbench/scripts/'+sid,'put',{'shared':True}).status_code==200 and sid in [s['id'] for s in request(b,'/workbench/scripts').json()])
    check('shared read-only',request(b,'/workbench/scripts/'+sid,'put',{'shared':False}).status_code==404)
    cookie=a.cookies.get('gee_session')
    csrf=requests.post(BASE+'/workbench/jobs',cookies={'gee_session':cookie},headers={'Origin':'https://unexpected.example'},json={'code':'print(1)'})
    check('cross-origin write denied',csrf.status_code==403)
    forged=requests.get(BASE+'/openeo/1.2/jobs',headers={'Authorization':'Bearer basic//YXVkaXRfYWxpY2U='})
    check('upstream forgeable development token rejected',forged.status_code==403 or forged.status_code==401)
    jid=request(a,'/workbench/jobs','post',{'title':'runner-check','code':'print(connection.list_collection_ids())'}).json()['id']
    check('foreign job log denied',request(b,f'/workbench/jobs/{jid}/logs').status_code==404)
    result=wait(a,jid);check('isolated Python official client',result['status']=='finished' and 'sentinel-2-l2a' in result['logs'],result)
    jid=request(a,'/workbench/jobs','post',{'title':'error-check','code':'raise RuntimeError("intentional acceptance error")'}).json()['id']
    result=wait(a,jid);check('script error visible',result['status']=='error' and 'intentional acceptance error' in result['logs'])
    jid=request(a,'/workbench/jobs','post',{'title':'cancel-check','code':'import time\ntime.sleep(90)'}).json()['id']
    request(a,f'/workbench/jobs/{jid}/cancel','post',{})
    check('cancel persists',wait(a,jid)['status']=='canceled')
    code='import socket\ntry:\n socket.create_connection(("1.1.1.1",443),timeout=2)\n print("UNEXPECTED_CONNECTION")\nexcept OSError:\n print("EGRESS_BLOCKED")'
    jid=request(a,'/workbench/jobs','post',{'title':'egress-check','code':code}).json()['id']
    result=wait(a,jid);check('script public IP egress blocked','EGRESS_BLOCKED' in result['logs'] and 'UNEXPECTED_CONNECTION' not in result['logs'])
    code='import os\nassert not any(k in os.environ for k in ["DATABASE_URL","CDSAPI_KEY","AWS_SECRET_ACCESS_KEY"])\nassert not os.path.exists("/var/run/docker.sock")\nassert not os.path.exists("/data/assets")\nprint("ISOLATED")'
    jid=request(a,'/workbench/jobs','post',{'title':'secrets-check','code':code}).json()['id']
    result=wait(a,jid);check('script has no data mount, docker socket, DB/provider secrets',result['status']=='finished' and 'ISOLATED' in result['logs'])
    caps=request(a,'/openeo/1.2/')
    check('API metadata is not browser cached',caps.headers.get('Cache-Control')=='no-store')
    check('hosted-service legal links removed',all(link['href'].startswith(BASE) for link in caps.json()['links']))
    check('cross-origin response is not enabled','Access-Control-Allow-Origin' not in caps.headers)
    check('foreign result download denied',request(a,'/workbench/jobs/0185ac3f-293c-42cb-9151-5afdcda4c782/files/openEO.tif').status_code==404)
    request(a,'/workbench/logout','post',{})
    check('logout immediately revokes session',requests.get(BASE+'/workbench/me',cookies={'gee_session':cookie}).status_code==401)
finally:
    (ROOT/'audit'/'api-integration.json').write_text(json.dumps(records,indent=2,ensure_ascii=False))
    print(json.dumps(records,indent=2,ensure_ascii=False))
