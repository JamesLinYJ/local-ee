"""Versioned management API. UI providers are clients, never authorization boundaries."""
from functools import wraps
from flask import Blueprint,request,jsonify,g
from .. import db
from ..http_auth import secure
from ..access import permits
from ..services import administration as service


def allowed(permission):
    def decorate(fn):
        @secure
        @wraps(fn)
        def guarded(*args,**kwargs):
            if not permits(g.account,permission):service.fail('没有管理权限',403,'PermissionDenied')
            return fn(*args,**kwargs)
        return guarded
    return decorate


def register_admin_api(app):
    bp=Blueprint('administration',__name__,url_prefix='/workbench/admin/v1')

    @bp.get('/<resource>')
    @secure
    def listing(resource):
        permission={'datasets':'datasets:manage','users':'users:manage','jobs':'jobs:manage','audit':'audit:read'}.get(resource)
        if not permission:service.fail('管理资源不存在',404,'AdminNotFound')
        if not permits(g.account,permission):service.fail('没有管理权限',403,'PermissionDenied')
        try:
            page=int(request.args.get('page','1'));size=int(request.args.get('page_size','25'))
            if page<1 or page>10000 or size<1 or size>100:raise ValueError()
        except ValueError:service.fail('分页参数无效')
        q=request.args.get('q','').strip()
        if len(q)>100:service.fail('查询文本过长')
        needle='%'+q.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
        definitions={
            'users':("users","id ILIKE %s ESCAPE '!'",'id,role,enabled,created','id'),
            'datasets':("collections c","c.id ILIKE %s ESCAPE '!'",'''c.id,c.metadata || c.managed_metadata AS metadata,c.enabled,c.revision,
              (SELECT count(*) FROM items i WHERE i.collection_id=c.id AND i.active) AS item_count''','c.id'),
            'jobs':("jobs","(title ILIKE %s ESCAPE '!' OR user_id ILIKE %s ESCAPE '!')",'id,user_id,kind,title,status,created,started,finished','created DESC,id DESC'),
            'audit':("audit_events","(actor ILIKE %s ESCAPE '!' OR object_id ILIKE %s ESCAPE '!')",'id,actor,action,object_type,object_id,changes,created','created DESC,id DESC'),
        }
        table,where,columns,order=definitions[resource]
        parameters=(needle,needle) if resource in {'jobs','audit'} else (needle,)
        # SQL fragments above are constants, never request-provided identifiers.
        with db.connect() as c:
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total=c.execute(f'SELECT count(*) AS n FROM {table} WHERE {where}',parameters).fetchone()['n']
            rows=c.execute(f'SELECT {columns} FROM {table} WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s',(*parameters,size,(page-1)*size)).fetchall()
        for row in rows:
            if resource=='jobs':row['id']=str(row['id'])
            if resource=='datasets':row['ready']=bool(row['item_count'] and row['metadata'].get('extent') and row['metadata'].get('cube:dimensions',{}).get('bands',{}).get('values'))
        return jsonify({'data':rows,'total':total})

    @bp.post('/datasets')
    @allowed('datasets:manage')
    def create_dataset():return jsonify({'data':service.dataset_create(g.account['user_id'],request.get_json())}),201

    @bp.patch('/datasets/<cid>')
    @allowed('datasets:manage')
    def update_dataset(cid):return jsonify({'data':service.dataset_update(g.account['user_id'],cid,request.get_json())})

    @bp.post('/users')
    @allowed('users:manage')
    def create_user():return jsonify({'data':service.user_create(g.account['user_id'],request.get_json())}),201

    @bp.patch('/users/<uid>')
    @allowed('users:manage')
    def update_user(uid):return jsonify({'data':service.user_update(g.account['user_id'],uid,request.get_json())})

    @bp.post('/jobs/<jid>/cancel')
    @allowed('jobs:manage')
    def cancel(jid):return jsonify({'data':service.cancel_job(g.account['user_id'],jid)})

    app.register_blueprint(bp)
