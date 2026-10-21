import io
import json
import logging
import os
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
import numpy as np
import rasterio
from rasterio.warp import transform_bounds, transform
from PIL import Image
from flask import request, jsonify, g, send_file, send_from_directory, abort
from psycopg.types.json import Jsonb
from openeo_driver.views import build_app
from openeo_driver.users import User
from . import db, auth
from .artifacts import artifact_path
from .backend import Backend, DATA

def create_app():
    db.init()
    backend = Backend()
    app = build_app(backend)
    app.config.update(MAX_CONTENT_LENGTH=1024*1024)
    auth.install(app.extensions["auth_handler"])
    # The upstream informational request logger includes bodies; suppress it.
    logging.getLogger("openeo_driver.views").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    from .http_auth import secure

    @app.after_request
    def private_headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        if request.path.startswith(("/workbench","/openeo","/gee","/.well-known")):
            response.headers["Cache-Control"]="no-store"
        response.headers.pop("Access-Control-Allow-Origin", None)
        return response

    if os.environ.get('GEE_RUNTIME') == 'native':
        import mimetypes
        # Use Python's built-in MIME table, avoiding unrelated host Apache config.
        mimetypes.knownfiles=[]
        mimetypes.init(files=[])
        frontend=Path(os.environ['GEE_PROJECT_ROOT'])/'web/dist'
        @app.get('/')
        @app.get('/<path:asset>')
        def native_frontend(asset='index.html'):
            if asset.split('/')[0] in {'workbench','openeo','gee','.well-known'}:
                abort(404)
            return send_from_directory(frontend,asset)
        # Upstream registers '/' first as an API redirect. Native deployment
        # owns the web origin, so replace that view without changing API routes.
        app.view_functions['redirect_root']=native_frontend

    @app.post("/workbench/login")
    def login():
        data=request.get_json() or {}
        if request.headers.get("Origin") != os.environ.get("PUBLIC_ORIGIN", "http://localhost:8787"): abort(403)
        if not auth.verify(str(data.get("username","")), str(data.get("password",""))): abort(401)
        token=auth.issue(data["username"])
        from .access import permissions
        account=auth.resolve(token)
        response=jsonify({"user":data["username"],"role":account['role'],"permissions":permissions(account['role'])})
        response.set_cookie("gee_session",token,httponly=True,samesite="Strict",secure=os.environ.get("COOKIE_SECURE")=="1",max_age=43200)
        return response
    @app.get("/workbench/me")
    @secure
    def me():
        from .access import permissions
        return jsonify({"user":g.account["user_id"],"role":g.account['role'],"permissions":permissions(g.account['role'])})
    @app.post("/workbench/logout")
    @secure
    def logout():
        auth.revoke(g.token)
        response=jsonify({"ok":True});response.delete_cookie("gee_session");return response

    @app.route("/workbench/scripts",methods=["GET","POST"])
    @secure
    def scripts():
        uid=g.account["user_id"]
        if request.method=="GET":
            return jsonify(db.query("SELECT * FROM scripts WHERE user_id=%s OR shared ORDER BY updated DESC",(uid,)))
        data=request.get_json() or {};code=data.get("code","");language=data.get("language","python")
        if language not in {"python","javascript"}: abort(400)
        if not isinstance(code,str) or len(code)>100000: abort(400)
        sid=str(uuid.uuid4())
        db.query("INSERT INTO scripts(id,user_id,title,code,shared,language) VALUES(%s,%s,%s,%s,%s,%s)",
                 (sid,uid,str(data.get("title") or "未命名脚本")[:200],code,bool(data.get("shared",False)),language))
        return jsonify({"id":sid}),201
    @app.route("/workbench/scripts/<sid>",methods=["PUT","DELETE"])
    @secure
    def script(sid):
        row=db.query("SELECT * FROM scripts WHERE id::text=%s AND user_id=%s",(sid,g.account["user_id"]),one=True)
        if not row: abort(404)
        if request.method=="DELETE": db.query("DELETE FROM scripts WHERE id=%s",(sid,))
        else:
            data=request.get_json() or {};code=data.get("code",row["code"]);language=data.get("language",row["language"])
            if language not in {"python","javascript"}: abort(400)
            if not isinstance(code,str) or len(code)>100000: abort(400)
            db.query("UPDATE scripts SET title=%s,code=%s,shared=%s,language=%s,updated=now() WHERE id=%s",
                     (str(data.get("title",row["title"]))[:200],code,bool(data.get("shared",row["shared"])),language,sid))
        return jsonify({"ok":True})

    @app.route("/workbench/jobs",methods=["GET","POST"])
    @secure
    def jobs():
        uid=g.account["user_id"]
        if request.method=="GET":
            return jsonify(db.query("SELECT id,kind,title,status,created,started,finished,error,assets,language,events,context FROM jobs WHERE user_id=%s ORDER BY created DESC LIMIT 100",(uid,)))
        data=request.get_json() or {};code=data.get("code");language=data.get("language","python")
        if language not in {"python","javascript"}: abort(400)
        if not isinstance(code,str) or not code.strip() or len(code)>100000: abort(400)
        with db.connect() as c:
            # Serialize per-user script submission quotas.
            c.execute("SELECT id FROM users WHERE id=%s FOR UPDATE",(uid,))
            if c.execute("SELECT count(*) AS n FROM jobs WHERE user_id=%s AND kind='script' AND status IN ('queued','running')",(uid,)).fetchone()["n"]>=5: abort(429)
            jid=str(uuid.uuid4())
            c.execute("INSERT INTO jobs(id,user_id,kind,title,status,code,language) VALUES(%s,%s,'script',%s,'queued',%s,%s)",
                      (jid,uid,str(data.get("title") or ("GEE JavaScript" if language=="javascript" else "Python 脚本"))[:200],code,language))
        return jsonify({"id":jid}),201
    @app.get("/workbench/jobs/<jid>/logs")
    @secure
    def logs(jid):
        row=db.job(jid,g.account["user_id"])
        return jsonify({k:row[k] for k in ("logs","status","error")})

    @app.post("/workbench/jobs/<jid>/start")
    @secure
    def start(jid):
        from openeo_driver.users import User
        backend.batch_jobs.start_job(jid, User(g.account['user_id']))
        return jsonify({'ok':True})

    @app.post("/workbench/jobs/<jid>/cancel")
    @secure
    def cancel(jid):
        backend.batch_jobs.cancel_job(jid,g.account["user_id"]);return jsonify({"ok":True})
    @app.post("/workbench/jobs/<jid>/retry")
    @secure
    def retry(jid):
        row=db.job(jid,g.account["user_id"])
        if row["status"] not in {"error","canceled","finished"}: abort(409)
        for snapshot in row['snapshot'].values():
            if any(i.get('collection')=='sentinel-2-l2a' and i.get('properties',{}).get('gee:source_collection')!='sentinel-2-c1-l2a' for i in snapshot['items']):
                return jsonify({'message':'旧数据源偏移存在歧义，请重新运行 Python 脚本以使用已校验的数据版本'}),409
        new=str(uuid.uuid4())
        with db.connect() as c:
            c.execute("SELECT id FROM users WHERE id=%s FOR UPDATE",(row['user_id'],))
            count=c.execute("SELECT count(*) AS n FROM jobs WHERE user_id=%s AND kind=%s AND status IN ('created','queued','running')",(row['user_id'],row['kind'])).fetchone()['n']
            if count >= (5 if row['kind']=='script' else 30): abort(429)
            c.execute("INSERT INTO jobs(id,user_id,kind,title,status,process,code,snapshot,language,context) VALUES(%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s)",
                (new,row["user_id"],row["kind"],row["title"],Jsonb(row["process"]),row["code"],Jsonb(row["snapshot"]),row["language"],Jsonb(row["context"])))
        return jsonify({"id":new}),201

    def artifact(jid,name):
        row=db.job(jid,g.account["user_id"])
        if row["status"]!="finished" or name not in row["assets"]: abort(404)
        try: return artifact_path(DATA,jid,name)
        except (ValueError,OSError): abort(404)
    @app.get("/workbench/jobs/<jid>/files/<name>")
    @secure
    def download(jid,name): return send_file(artifact(jid,name),as_attachment=True,conditional=True)
    @app.get("/workbench/jobs/<jid>/raster/<name>")
    @secure
    def raster_info(jid,name):
        with rasterio.open(artifact(jid,name)) as src:
            bounds=transform_bounds(src.crs,"EPSG:4326",*src.bounds)
            return jsonify({"bounds":bounds,"bands":src.count,"crs":str(src.crs),"nodata":str(src.nodata),"width":src.width,"height":src.height})
    @app.get("/workbench/jobs/<jid>/preview/<name>")
    @secure
    def preview(jid,name):
        from rasterio.vrt import WarpedVRT
        from .services.ee import visualization
        from .services.raster_preview import rgba
        try:
            raw=request.args.get('vis','{}')
            if len(raw)>8192:raise ValueError('Preview style is too large')
            style=visualization(json.loads(raw))
            for key in ['min','max']:
                if key in request.args:style[key]=float(request.args[key])
            with rasterio.open(artifact(jid,name)) as src, WarpedVRT(src,crs="EPSG:4326") as vrt:
                scale=min(1,1024/max(vrt.width,vrt.height))
                indexes=list(range(1,4)) if src.count>=3 else [1]
                if style.get('bands'):
                    row=db.job(jid,g.account['user_id'])
                    labels=row['context'].get('bands') or list(src.descriptions)
                    indexes=[labels.index(label)+1 for label in style['bands']]
                    if len(indexes) not in {1,3}:raise ValueError('Preview requires one or three bands')
                array=vrt.read(indexes,out_shape=(len(indexes),max(1,int(vrt.height*scale)),max(1,int(vrt.width*scale))),masked=True)
            pixels=rgba(array,style,request.args.get('palette','vegetation'))
        except (ValueError,TypeError,IndexError,KeyError):abort(400)
        stream=io.BytesIO();Image.fromarray(pixels).save(stream,format="PNG");stream.seek(0)
        return send_file(stream,mimetype="image/png")
    @app.get("/workbench/jobs/<jid>/pixel/<name>")
    @secure
    def pixel(jid,name):
        try:
            lon,lat=float(request.args["lon"]),float(request.args["lat"])
            if not (-180<=lon<=180 and -90<=lat<=90): abort(400)
        except (KeyError,ValueError): abort(400)
        with rasterio.open(artifact(jid,name)) as src:
            x,y=transform("EPSG:4326",src.crs,[lon],[lat]);row,col=src.index(x[0],y[0])
            if not (0<=row<src.height and 0<=col<src.width): return jsonify({"values":None})
            vals=next(src.sample([(x[0],y[0])],masked=True))
            return jsonify({"values":[None if np.ma.is_masked(v) or not np.isfinite(v) else float(v) for v in vals]})
    @app.get("/workbench/catalog")
    @secure
    def catalog(): return jsonify(backend.catalog.get_all_metadata())
    @app.get('/workbench/catalog/<iid>/assets/<asset>')
    @secure
    def catalog_asset(iid,asset):
        row=db.query('SELECT i.metadata FROM items i JOIN collections c ON c.id=i.collection_id WHERE i.id=%s AND i.active AND c.enabled',(iid,),one=True)
        if not row or asset not in row['metadata']['assets']:abort(404)
        href=row['metadata']['assets'][asset]['href']
        path=DATA/href.removeprefix('/data/')
        if not path.resolve().is_relative_to((DATA/'assets').resolve()) or path.is_symlink():abort(404)
        return send_file(path,conditional=True)
    @app.get("/workbench/examples")
    @secure
    def examples():
        return jsonify([{ "name":p.stem,"code":p.read_text(),"language":"python" if p.suffix==".py" else "javascript"} for p in sorted(Path("examples").rglob("*")) if p.suffix in {".py",".js"}])
    # Flask runs after-request hooks in reverse order. Clear CORS after upstream hooks.
    app.after_request_funcs[None].remove(private_headers)
    app.after_request_funcs[None].insert(0,private_headers)
    from .api.ee import register_ee_api
    register_ee_api(app, backend)
    from .api.admin import register_admin_api
    register_admin_api(app)
    from .api.dataset_files import register_file_api
    register_file_api(app)
    return app
