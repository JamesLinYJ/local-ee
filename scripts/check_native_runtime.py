"""Native HTTP/runtime acceptance; restarts only the project scheduler and creates an unpublished fixture."""
import importlib.util,os,json,time,hashlib,io,sys
from pathlib import Path
import requests,numpy as np,rasterio
from rasterio.transform import from_origin
from rasterio.io import MemoryFile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
AUDIT=Path(os.environ['GEE_AUDIT_DIR']);AUDIT.mkdir(parents=True,exist_ok=False)
spec=importlib.util.spec_from_file_location('native',ROOT/'scripts/native.py');native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native);os.environ.update(native.environment())
from gee import db
BASE='http://localhost:8787';session=requests.Session();session.headers['Origin']=BASE
login=dict(line.split(': ',1) for line in (ROOT/'deploy/native-login.txt').read_text().splitlines())
report=[]
def check(name,passed,**extra):
 assert passed,(name,extra)
 value={'test':name,'passed':bool(passed),**extra};report.append(value);print(value,flush=True)
def request(path,method='get',**kwargs):
 r=getattr(session,method)(BASE+path,timeout=15,**kwargs);r.raise_for_status();return r
request('/workbench/login','post',json={'username':login['Username'],'password':login['Password']})
check('native frontend served directly',request('/').headers['Content-Type'].startswith('text/html'))
examples=request('/workbench/examples').json();check('local Python and GEE JavaScript examples',{'python','javascript'}<={e['language'] for e in examples},count=len(examples))
def submit(code,language='python'):
 return request('/workbench/jobs','post',json={'title':'原生验收 · '+language,'language':language,'code':code}).json()['id']
def until(jid,states,timeout=30):
 deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  row=request('/workbench/jobs/'+jid+'/logs').json()
  if row['status'] in states:return row
  time.sleep(.4)
 raise RuntimeError('Task timeout '+jid)
jid=submit('import time\ntime.sleep(8)\nprint("RECOVERED")')
until(jid,{'running'})
state=ROOT/'.native/run/tasks'/f'{jid}.state.json'
while not state.exists():time.sleep(.1)
identity=json.loads(state.read_text())['pid'];native.stop_service('worker');native.start()
value=until(jid,{'finished','error'})
check('worker restart preserves running supervisor',value['status']=='finished' and 'RECOVERED' in value['logs'] and json.loads(state.read_text())['pid']==identity,job_id=jid)
jid=submit('import time\ntime.sleep(60)');until(jid,{'running'});request('/workbench/jobs/'+jid+'/cancel','post',json={})
until(jid,{'canceled'});time.sleep(3)
state=json.loads((ROOT/'.native/run/tasks'/f'{jid}.state.json').read_text())
check('cancel stops native process group',state['status']=='exited' and state['exit_code']!=0,job_id=jid)
jid=submit('raise RuntimeError("expected native script failure")');value=until(jid,{'finished','error'})
check('script failure is explicit',value['status']=='error' and 'expected native script failure' in value['logs'],job_id=jid)
code='''import os,pathlib,socket
assert not any(key in os.environ for key in ['DATABASE_URL','CDSAPI_KEY','AWS_SECRET_ACCESS_KEY'])
for path in [%r,%r,%r]:
 try:pathlib.Path(path).read_bytes();raise RuntimeError('HOST FILE VISIBLE')
 except PermissionError:pass
for host,port in [('198.51.100.1',443),('127.0.0.1',55432)]:
 try:socket.create_connection((host,port),timeout=1);raise RuntimeError('FORBIDDEN NETWORK VISIBLE')
 except PermissionError:pass
print('ISOLATED')
'''%(str(ROOT/'.env'),str(ROOT/'.native/config.json'),str(ROOT/'data/assets/sentinel-2-l2a'/next((ROOT/'data/assets/sentinel-2-l2a').iterdir()).name/'red.tif'))
jid=submit(code);value=until(jid,{'finished','error'});check('script host files credentials and forbidden network denied',value['status']=='finished' and 'ISOLATED' in value['logs'],job_id=jid)
jid=submit('console.log(process.env.OPENEO_TOKEN);','javascript');value=until(jid,{'finished','error'})
check('script token redacted and revoked after completion',value['status']=='finished' and '[REDACTED]' in value['logs'] and db.query('SELECT count(*) AS n FROM tokens WHERE job_id=%s',(jid,),one=True)['n']==0,job_id=jid)
# Real HTTP upload -> queue -> Seatbelt normalizer -> immutable publication -> download.
base='/workbench/admin/v1';cid='native-file-check-'+str(int(time.time()))
request(base+'/datasets','post',json={'id':cid,'title':'原生文件验收 · 合成数据','description':'Synthetic only; kept unpublished','license':'proprietary'})
source=AUDIT/'source.tif';raw=np.array([[[0,2,4],[6,8,10]],[[1,0,3],[4,5,6]]],dtype='int16')
with rasterio.open(source,'w',driver='GTiff',width=3,height=2,count=2,dtype='int16',nodata=0,crs='EPSG:4326',transform=from_origin(110,30,.01,.01)) as f:
 f.write(raw);f.scales=(.5,2);f.offsets=(1,-1)
content=source.read_bytes();digest=hashlib.sha256(content).hexdigest()
fid=request(base+'/datasets/'+cid+'/files','post',json={'filename':'原生测试影像.tif','size':len(content),'sha256':digest}).json()['data']['id'];path=base+'/uploads/'+fid
for offset,part in [(0,content[:100]),(100,content[100:])]:
 request(path+'/content','put',data=part,headers={'Content-Type':'application/octet-stream','Upload-Offset':str(offset)})
request(path+'/complete','post',json={})
original=request(path+'/download');check('native original download preserves SHA256',hashlib.sha256(original.content).hexdigest()==digest)
jid=request(path+'/ingest','post',json={'datetime':'2024-01-19T00:00:00Z','unit':'1','bands':['red','nir']}).json()['data']['job_id'];value=until(jid,{'finished','error'},60)
check('actual native GeoTIFF ingestion succeeds',value['status']=='finished',job_id=jid,error=value['error'])
for index,(band,scale,offset) in enumerate([('red',.5,1),('nir',2,-1)]):
 data=request(base+'/datasets/'+cid+'/assets/upload-'+fid+'/'+band+'/download').content;(AUDIT/(band+'.tif')).write_bytes(data)
 with MemoryFile(data) as mem,mem.open() as f:
  actual=f.read(1,masked=True);expected=raw[index]*scale+offset
  check('native COG '+band+' values and mask',np.array_equal(np.ma.getmaskarray(actual),raw[index]==0) and np.array_equal(actual.compressed(),expected[raw[index]!=0]))
check('ingestion does not publish draft',cid not in {c['id'] for c in request('/workbench/catalog').json()})
(AUDIT/'validation.json').write_text(json.dumps({'checks':report,'passed':all(x['passed'] for x in report),'dataset_id':cid,'synthetic_dataset_kept_unpublished':True},ensure_ascii=False,indent=2)+'\n')
