"""Benign acceptance controls against a disposable restored database, never production.

Run inside the candidate API image with DATABASE_URL naming gee_admin_check_*.
No passwords, tokens, scientific data or private scripts are printed.
"""
import json
import os
import secrets
from urllib.parse import urlsplit
from uuid import uuid4
from psycopg.types.json import Jsonb
from gee import auth,db
from gee.migrations import migrate
from gee.app import create_app

if not urlsplit(os.environ['DATABASE_URL']).path.removeprefix('/').startswith('gee_admin_check_'):
    raise SystemExit('Refusing to run outside a disposable administration test database')
migrate();migrate();db.init()
before=db.query('SELECT (SELECT count(*) FROM scripts) AS scripts,(SELECT count(*) FROM jobs) AS jobs,(SELECT count(*) FROM items) AS items',one=True)
original_users=db.query('SELECT id,role,enabled FROM users ORDER BY id')
prefix='check_'+uuid4().hex[:10]
password=secrets.token_urlsafe(24)
names={role:prefix+'_'+role for role in ['admin','dataset_manager','researcher','viewer']}
for role,name in names.items():auth.create_user(name,password,role=role)
app=create_app();app.config['TESTING']=True
origin=os.environ.get('PUBLIC_ORIGIN','http://localhost:8787')
clients={}
for role,name in names.items():
    client=app.test_client()
    response=client.post('/workbench/login',json={'username':name,'password':password},headers={'Origin':origin})
    assert response.status_code==200,(role,response.status_code)
    assert response.json['role']==role
    clients[role]=client
admin=clients['admin'];manager=clients['dataset_manager'];viewer=clients['viewer'];researcher=clients['researcher']
base='/workbench/admin/v1'
checks=[]
def expect(response,status,label):
    assert response.status_code==status,(label,response.status_code,response.get_data(as_text=True)[:200])
    checks.append(label)
    return response.json
expect(researcher.get(base+'/datasets'),403,'researcher cannot manage datasets')
expect(manager.get(base+'/users'),403,'dataset manager cannot manage users')
expect(manager.get(base+'/audit'),403,'dataset manager cannot read global audit')
expect(viewer.post('/workbench/jobs',json={'language':'javascript','code':'print(1)'},headers={'Origin':origin}),403,'viewer cannot submit scripts')
expect(viewer.post('/openeo/1.2/jobs',json={'process':{}},headers={'Authorization':'Bearer basic//'+auth.issue(names['viewer'])}),403,'viewer cannot submit via openEO')
script_client=app.test_client()
expect(script_client.get(base+'/users',headers={'Authorization':'Bearer basic//'+auth.issue(names['admin'],scope='script')}),403,'script token cannot enter administration')
draft=prefix+'-draft'
row=expect(manager.post(base+'/datasets',json={'id':draft,'title':'验收目录草稿','description':'Disposable test metadata','license':'proprietary'},headers={'Origin':origin}),201,'dataset manager creates draft')['data']
assert not row['enabled'] and not row['ready'] and row['item_count']==0
expect(manager.patch(base+'/datasets/'+draft,json={'enabled':True,'revision':1},headers={'Origin':origin}),409,'empty draft cannot be published')
expect(manager.patch(base+'/datasets/'+draft,json={'title':'更新后的草稿','revision':1},headers={'Origin':origin}),200,'metadata update with revision')
expect(manager.patch(base+'/datasets/'+draft,json={'title':'过期修改','revision':1},headers={'Origin':origin}),409,'stale dataset revision is rejected')
expect(manager.patch(base+'/datasets/'+draft,json={'revision':2,'assets':{}},headers={'Origin':origin}),400,'scientific asset fields cannot be rewritten')
catalog=admin.get('/workbench/catalog').json
assert draft not in {c['id'] for c in catalog}
checks.append('draft is absent from workbench catalog')
live=db.query('SELECT id,revision FROM collections WHERE enabled AND id IN (SELECT collection_id FROM items WHERE active) ORDER BY id LIMIT 1',one=True)
if live:
    item=db.query('SELECT metadata FROM items WHERE collection_id=%s AND active LIMIT 1',(live['id'],),one=True)['metadata']
    asset=next(iter(item['assets']))
    expect(admin.patch(base+'/datasets/'+live['id'],json={'enabled':False,'revision':live['revision']},headers={'Origin':origin}),200,'administrator unpublishes existing collection')
    assert live['id'] not in {c['id'] for c in admin.get('/workbench/catalog').json}
    expect(admin.get('/openeo/1.2/collections/'+live['id']),404,'unpublished collection unavailable through openEO')
    expect(admin.get('/workbench/catalog/'+item['id']+'/assets/'+asset),404,'unpublished original asset cannot be fetched')
    expect(admin.patch(base+'/datasets/'+live['id'],json={'enabled':True,'revision':live['revision']+1},headers={'Origin':origin}),200,'administrator republishes existing collection')
sessions=auth.issue(names['researcher'])
jid=str(uuid4())
db.query("INSERT INTO jobs(id,user_id,kind,title,status) VALUES(%s,%s,'script','Disposable queued control','queued')",(jid,names['researcher']))
expect(admin.patch(base+'/users/'+names['researcher'],json={'enabled':False},headers={'Origin':origin}),200,'administrator disables account')
expect(researcher.get('/workbench/me'),401,'disabled account existing cookie no longer works')
expect(script_client.get('/workbench/me',headers={'Authorization':'Bearer basic//'+sessions}),401,'disabled account bearer session no longer works')
assert db.query('SELECT status FROM jobs WHERE id=%s',(jid,),one=True)['status']=='canceled'
checks.append('disable cancels pending tasks')
expect(admin.patch(base+'/users/'+names['admin'],json={'role':'viewer'},headers={'Origin':origin}),409,'last administrator cannot be demoted')
users=expect(admin.get(base+'/users'),200,'administrator can list users')
assert all(set(u)=={'id','role','enabled','created'} for u in users['data'])
events=expect(admin.get(base+'/audit'),200,'administrator can read management audit')
encoded=json.dumps(events)
assert password not in encoded and sessions not in encoded
assert any(e['object_id']==draft and e['action']=='dataset.create' for e in events['data'])
checks.append('management audit excludes passwords and session tokens')
for row in original_users:
    assert db.query('SELECT id,role,enabled FROM users WHERE id=%s',(row['id'],),one=True)==row
after=db.query('SELECT (SELECT count(*) FROM scripts) AS scripts,(SELECT count(*) FROM jobs) AS jobs,(SELECT count(*) FROM items) AS items',one=True)
assert after=={**before,'jobs':before['jobs']+1}
print(json.dumps({'checks':checks,'passed':len(checks),'migrations':[r['version'] for r in db.query('SELECT version FROM schema_migrations ORDER BY version')],'original_counts':before,'original_accounts_preserved':True,'existing_research_rows_preserved':True,'disposable_database':True},ensure_ascii=False,indent=2))
