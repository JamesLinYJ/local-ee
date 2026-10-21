"""Five users enqueue real GeoTrellis jobs; verify serial execution and isolation."""
import json,secrets,subprocess,time
from pathlib import Path
import openeo,requests
root=Path(__file__).resolve().parents[1];base='http://localhost:8787'
accounts=[('audit_team_'+str(i),secrets.token_urlsafe(20)) for i in range(5)]
code='from gee import auth\n'+''.join('auth.create_user('+repr(u)+','+repr(p)+')\n' for u,p in accounts)
subprocess.run(['docker-compose','exec','-T','api','python','-'],input=code,text=True,check=True,cwd=root)
connections=[];jobs=[]
for username,password in accounts:
 c=openeo.connect(base+'/openeo/1.2').authenticate_basic(username,password);connections.append(c)
 cube=c.load_collection('sentinel-2-l2a',spatial_extent=dict(west=113.55,south=22.30,east=113.57,north=22.32),temporal_extent=['2024-01-19','2024-01-20'],bands=['red','nir'])
 j=cube.ndvi(nir='nir',red='red').mean_time().save_result('GTiff').create_job(title='五用户排队验收');j.start_job();jobs.append(j)
max_running=0;seen_queued=False
for _ in range(180):
 statuses=[j.describe_job()['status'] for j in jobs]
 max_running=max(max_running,statuses.count('running'));seen_queued |= 'queued' in statuses
 if all(s in ['finished','error','canceled'] for s in statuses):break
 time.sleep(1)
ids=[j.job_id for j in jobs]
query='from gee import db; import json; print(json.dumps(db.query("SELECT id,started,finished,status FROM jobs WHERE id=ANY(%s::uuid[]) ORDER BY started",('+repr(ids)+',)),default=str))'
rows=json.loads(subprocess.check_output(['docker-compose','exec','-T','api','python','-c',query],text=True,cwd=root))
serial=all(rows[i]['finished']<=rows[i+1]['started'] for i in range(len(rows)-1))
isolation=[]
for i,c in enumerate(connections):
 other=ids[(i+1)%5]
 try:c.get('/jobs/'+other+'/results');denied=False
 except Exception as e:denied=getattr(e,'http_status_code',None)==404
 isolation.append(denied)
report={'users':5,'jobs':rows,'max_running_observed':max_running,'queued_observed':seen_queued,'no_overlap_from_database':serial,'foreign_results_denied':isolation,'all_finished':all(s=='finished' for s in statuses),'scope':'small real local Sentinel-2 sample, not a throughput benchmark'}
report['passed']=report['all_finished'] and serial and seen_queued and all(isolation) and max_running<=1
(root/'audit/team-queue.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,indent=2));assert report['passed']
