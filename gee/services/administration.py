"""Administrative use cases. Never return secrets, scripts or other users' results."""
import re
from psycopg.types.json import Jsonb
from werkzeug.security import generate_password_hash
from openeo_driver.errors import OpenEOApiException
from .. import db
from ..access import ROLES


def fail(message, status=400, code='AdminInvalidRequest'):
    raise OpenEOApiException(message, code=code, status_code=status)


def text(value, name, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        fail(f'{name} 必须是有效文本（最多 {limit} 字符）')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        fail(f'{name} 包含控制字符')
    return value.strip()


def fields(data, allowed):
    if not isinstance(data, dict) or set(data) - set(allowed):
        fail('请求包含未知字段')


def audit(connection, actor, action, kind, object_id, changes):
    connection.execute('''INSERT INTO audit_events(actor,action,object_type,object_id,changes)
        VALUES(%s,%s,%s,%s,%s)''', (actor or 'local-console', action, kind, object_id, Jsonb(changes)))


def actor_check(connection, actor, permission):
    # CLI recovery is deliberately separate from all HTTP callers.
    if actor is None:
        return
    row=connection.execute('SELECT role,enabled FROM users WHERE id=%s FOR SHARE',(actor,)).fetchone()
    if not row or not row['enabled'] or permission not in ROLES.get(row['role'], ()):
        fail('没有执行此操作的权限',403,'PermissionDenied')


def user_create(actor, data):
    fields(data, {'id','password','role'})
    name=text(data.get('id'),'账号',64)
    password=data.get('password')
    role=data.get('role','researcher')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',name):fail('账号仅限字母数字 ._-')
    if not isinstance(password,str) or not 12 <= len(password) <= 1024:fail('密码须为 12 至 1024 字符')
    if not isinstance(role,str) or role not in ROLES:fail('未知角色')
    hashed=generate_password_hash(password)
    with db.connect() as c:
        c.execute('SELECT pg_advisory_xact_lock(1879645012)')
        actor_check(c,actor,'users:manage')
        row=c.execute('INSERT INTO users(id,password,role) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id,role,enabled,created',
                      (name,hashed,role)).fetchone()
        if not row:fail('账号已存在',409,'AdminConflict')
        audit(c,actor,'user.create','user',name,{'role':role})
    return row


def user_update(actor, name, data):
    fields(data,{'role','enabled','password'})
    if not data:fail('没有需要修改的字段')
    if 'role' in data and (not isinstance(data['role'],str) or data['role'] not in ROLES):fail('未知角色')
    if 'enabled' in data and type(data['enabled']) is not bool:fail('enabled 必须为布尔值')
    hashed=None
    if 'password' in data:
        if not isinstance(data['password'],str) or not 12 <= len(data['password']) <= 1024:fail('密码须为 12 至 1024 字符')
        hashed=generate_password_hash(data['password'])
    with db.connect() as c:
        # Serialize all administrator membership changes, including CLI recovery.
        c.execute('SELECT pg_advisory_xact_lock(1879645012)')
        actor_check(c,actor,'users:manage')
        old=c.execute('SELECT id,role,enabled,created FROM users WHERE id=%s FOR UPDATE',(name,)).fetchone()
        if not old:fail('账号不存在',404,'AdminNotFound')
        role=data.get('role',old['role']);enabled=data.get('enabled',old['enabled'])
        if old['role']=='admin' and old['enabled'] and (role!='admin' or not enabled):
            if c.execute("SELECT count(*) AS n FROM users WHERE role='admin' AND enabled").fetchone()['n'] <= 1:
                fail('必须保留至少一个启用的管理员',409,'LastAdministrator')
        c.execute('UPDATE users SET role=%s,enabled=%s,password=COALESCE(%s,password) WHERE id=%s',(role,enabled,hashed,name))
        # Demotion, password reset and disable take effect on the next request.
        c.execute('DELETE FROM tokens WHERE user_id=%s',(name,))
        canceled=0
        if not enabled:
            canceled=c.execute("UPDATE jobs SET status='canceled',finished=now(),updated=now() WHERE user_id=%s AND status IN ('created','queued','running')",(name,)).rowcount
        changes={'before':{'role':old['role'],'enabled':old['enabled']},'after':{'role':role,'enabled':enabled},'sessions_revoked':True,'tasks_canceled':canceled}
        if hashed:changes['password_reset']=True
        audit(c,actor,'user.update','user',name,changes)
    return {**old,'role':role,'enabled':enabled}


def dataset_create(actor,data):
    fields(data,{'id','title','description','license'})
    cid=text(data.get('id'),'数据集 ID',96)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}',cid):fail('数据集 ID 仅限字母数字 ._-')
    overlay={key:text(data.get(key,''),key,4000 if key=='description' else 200,required=key in {'title','license'}) for key in ('title','description','license')}
    # A draft is not published as a complete STAC Collection until ingestion adds extent/dimensions/items.
    metadata={'id':cid,'type':'Collection','stac_version':'1.0.0','links':[],**overlay}
    with db.connect() as c:
        actor_check(c,actor,'datasets:manage')
        row=c.execute('INSERT INTO collections(id,metadata,managed_metadata,enabled) VALUES(%s,%s,%s,false) ON CONFLICT DO NOTHING RETURNING id,revision',
                      (cid,Jsonb(metadata),Jsonb(overlay))).fetchone()
        if not row:fail('数据集 ID 已存在',409,'AdminConflict')
        audit(c,actor,'dataset.create','dataset',cid,{'metadata':overlay,'enabled':False})
    return {**row,'metadata':metadata,'enabled':False,'item_count':0,'ready':False}


def dataset_update(actor,cid,data):
    fields(data,{'title','description','license','enabled','revision'})
    if type(data.get('revision')) is not int or data['revision'] < 1:fail('必须提供数据集 revision')
    updates={k:text(data[k],k,4000 if k=='description' else 200,required=k!='description') for k in ('title','description','license') if k in data}
    if 'enabled' in data and type(data['enabled']) is not bool:fail('enabled 必须为布尔值')
    with db.connect() as c:
        actor_check(c,actor,'datasets:manage')
        row=c.execute('SELECT * FROM collections WHERE id=%s FOR UPDATE',(cid,)).fetchone()
        if not row:fail('数据集不存在',404,'AdminNotFound')
        if row['revision']!=data['revision']:fail('数据集已被其他管理员修改，请刷新后重试',409,'RevisionConflict')
        enabled=data.get('enabled',row['enabled'])
        count=c.execute('SELECT count(*) AS n FROM items WHERE collection_id=%s AND active',(cid,)).fetchone()['n']
        metadata=row['metadata']
        ready=bool(count and metadata.get('extent') and metadata.get('cube:dimensions',{}).get('bands',{}).get('values'))
        if enabled and not ready:fail('数据集尚无入库影像或缺少分析元数据，不能发布',409,'DatasetNotReady')
        overlay={**row['managed_metadata'],**updates}
        c.execute('UPDATE collections SET enabled=%s,managed_metadata=%s,revision=revision+1 WHERE id=%s',(enabled,Jsonb(overlay),cid))
        audit(c,actor,'dataset.update','dataset',cid,{'before':{'enabled':row['enabled'],'metadata':row['managed_metadata']},'after':{'enabled':enabled,'metadata':overlay},'revision':row['revision']+1})
    return {'id':cid,'metadata':{**metadata,**overlay},'enabled':enabled,'revision':row['revision']+1,'item_count':count,'ready':ready}


def cancel_job(actor,jid):
    with db.connect() as c:
        actor_check(c,actor,'jobs:manage')
        row=c.execute('SELECT id,status,kind FROM jobs WHERE id::text=%s FOR UPDATE',(jid,)).fetchone()
        if not row:fail('任务不存在',404,'AdminNotFound')
        if row['status'] not in {'created','queued','running'}:fail('任务已结束，不能取消',409,'JobNotCancelable')
        count=c.execute("UPDATE jobs SET status='canceled',finished=now(),updated=now() WHERE id=%s OR (context->>'source_job_id'=%s AND status IN ('created','queued','running'))",(row['id'],str(row['id']))).rowcount
        audit(c,actor,'job.cancel','job',jid,{'previous_status':row['status'],'tasks_canceled':count})
    return {'id':jid,'status':'canceled'}
