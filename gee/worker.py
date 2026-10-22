"""Durable macOS task queue with detached, Seatbelt-restricted native processes."""
import json
import mimetypes
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from .native.runtime import NativeClient, NotFound
from psycopg.types.json import Jsonb
from . import db, graph, auth
from .artifacts import artifact_path, output_dir

ROOT=Path(os.environ.get("DATA_ROOT","/data"))
LIMITS={"batch":int(os.environ.get("JOB_TIMEOUT","1800")),"script":120,"ingest":180}

def prepare(row):
    jid=str(row["id"]);folder=ROOT/"jobs"/jid
    folder.mkdir(parents=True,exist_ok=True);(folder/"out").mkdir(exist_ok=True)
    if row["kind"]=="batch":
        for catalog_id,(cid,selection) in graph.collection_loads(row["process"]["process_graph"]).items():
            snapshot=row['snapshot'][cid]
            source_items=snapshot['items']
            if selection is not None:
                by_id={item['id']:item for item in source_items}
                if any(i not in by_id for i in selection):raise ValueError('Selected data version is no longer active; resubmit the script')
                source_items=[by_id[i] for i in selection]
            catalog=dict(snapshot["collection"])
            catalog["type"]="Collection";catalog["stac_version"]="1.0.0";catalog["links"]=[]
            catalog['stac_extensions']=['https://stac-extensions.github.io/datacube/v2.2.0/schema.json','https://stac-extensions.github.io/eo/v1.1.0/schema.json']
            for i,item in enumerate(source_items):
                filename=f"item-{catalog_id}-{i}.json"
                doc=json.loads(json.dumps(item));doc["links"]=[]
                for asset in doc.get("assets",{}).values():
                    href=asset.get("href","")
                    if not isinstance(href,str) or not href.startswith("/data/assets/"):raise ValueError("Only local asset paths are allowed")
                    from .services.dataset_files import physical
                    asset["href"]=str(physical(ROOT/"assets",href.removeprefix("/data/assets/")))
                (folder/filename).write_text(json.dumps(doc))
                catalog["links"].append({"rel":"item","href":str(folder/filename),"type":"application/geo+json"})
            (folder/f"catalog-{catalog_id}.json").write_text(json.dumps(catalog))
        compiled=graph.materialize(row["process"]["process_graph"],row["snapshot"],str(folder))
        (folder/"graph.json").write_text(json.dumps(compiled))
    elif row['kind']=='ingest':
        from .services.local_ingest import prepare as prepare_ingest
        prepare_ingest(row,folder)
    else:
        (folder/("script.js" if row.get("language")=="javascript" else "script.py")).write_text(row["code"])
    for p in [folder,folder/"out",*folder.glob("*.json"),*folder.glob("*.py"),*folder.glob("*.js")]:
        p.chmod(0o750 if p.is_dir() else 0o640)
    return folder

def launch(client,row):
    prepare(row)
    return client.launch(row)


def finish(row,container):
    jid=str(row["id"])
    # Bound logs before decoding; no credentials or bearer tokens persisted by this worker.
    logs=auth.redact(container.logs(tail=2000).decode("utf-8",errors="replace")[-200000:])
    for value in container.attrs.get("Config",{}).get("Env",[]):
        if value.startswith("OPENEO_TOKEN="): logs=logs.replace(value.split("=",1)[1],"[REDACTED]")
    state=container.attrs["State"];code=state.get("ExitCode",1)
    status="finished" if code==0 else "error"
    error=None if code==0 else ("内存超限" if state.get("OOMKilled") else f"进程退出码 {code}；请查看日志")
    assets={}
    if status=="finished" and row["kind"]=="batch":
        try:
            from .services.ee_exports import finalize_export
            finalize_export(ROOT,row)
            folder=output_dir(ROOT,jid)
            runtime_json=(row.get('context',{}).get('protocol')=='earthengine'
                          and row.get('context',{}).get('result_kind')=='runtime_json')
            for path in folder.iterdir():
                if path.suffix.lower() in {".tif",".tiff",".nc",".csv"}:
                    path=artifact_path(ROOT,jid,path.name)
                    assets[path.name]={"type":{".tif":"image/tiff; application=geotiff",".tiff":"image/tiff; application=geotiff",".nc":"application/x-netcdf",".csv":"text/csv"}[path.suffix.lower()],"roles":["data"],"file:size":path.stat().st_size}
                elif runtime_json and path.name=='openEO.json':
                    path=artifact_path(ROOT,jid,path.name)
                    assets[path.name]={'type':'application/json','roles':['data'],'file:size':path.stat().st_size}
            if runtime_json:
                from .services.ee_runtime_results import read_result
                read_result(ROOT,{**row,'assets':assets})
        except (ValueError,OSError):
            assets={};status="error";error="结果目录或文件不符合隔离要求"
        if not assets: status="error";error="计算没有生成支持的结果文件"
    if row['kind']=='ingest':
        if status=='error' and logs.strip():error=auth.redact(logs.strip().splitlines()[-1])[:1000]
        current=db.query('SELECT status FROM jobs WHERE id=%s',(jid,),one=True)['status']
        if status=='finished' and current=='running':
            try:
                from .services.local_ingest import publish
                publish(ROOT,row)
            except Exception as failure:
                status='error';error=auth.redact(str(failure))[:1000]
        if status!='finished' or current!='running':
            db.query("UPDATE dataset_files SET status='error',error=%s,updated=now() WHERE job_id=%s AND status IN ('queued','processing')",(error or auth.redact(logs[-1000:]) or '入库任务已停止',jid))
        elif status=='finished':
            db.query('UPDATE jobs SET logs=%s WHERE id=%s',(logs,jid))
    db.query("UPDATE jobs SET status=%s,error=%s,logs=%s,assets=%s,updated=now(),finished=now() WHERE id=%s AND status='running'",
             (status,error,logs,Jsonb(assets),jid))
    # Revoke the per-script token after termination.
    for value in container.attrs.get("Config",{}).get("Env",[]):
        if value.startswith("OPENEO_TOKEN="): auth.revoke(value.split("=",1)[1])
    db.query("DELETE FROM tokens WHERE job_id=%s AND scope='script'",(jid,))
    container.remove()

def tick(client):
    for row in db.query("SELECT * FROM jobs WHERE status IN ('running','canceled')"):
        jid=str(row["id"])
        try: container=client.get("gee-"+jid)
        except NotFound:
            if row["status"]=="running":
                db.query("UPDATE jobs SET status='error',error='执行进程丢失；可重新提交',finished=now(),updated=now() WHERE id=%s AND status='running'",(jid,))
                db.query("DELETE FROM tokens WHERE job_id=%s AND scope='script'",(jid,))
            continue
        elapsed=(datetime.now(timezone.utc)-row["started"]).total_seconds() if row["started"] else 0
        if row["status"]=="canceled" or elapsed>LIMITS[row["kind"]]:
            container.stop(timeout=3);container.reload()
            if elapsed>LIMITS[row["kind"]] and row["status"]!="canceled":
                db.query("UPDATE jobs SET status='error',error='执行超时',finished=now(),updated=now() WHERE id=%s AND status='running'",(jid,))
            # Store final log even for a canceled job, without replacing its status.
            logs=auth.redact(container.logs(tail=1000).decode(errors="replace")[-100000:])
            for env in container.attrs['Config'].get('Env',[]):
                if env.startswith('OPENEO_TOKEN='): logs=logs.replace(env.split('=',1)[1],'[REDACTED]')
            db.query("UPDATE jobs SET logs=%s WHERE id=%s",(logs,jid))
            finish(row,container)
        elif container.status in {"exited","dead"}: finish(row,container)
        else:
            # Readback of active logs, bounded and redacted.
            logs=auth.redact(container.logs(tail=500).decode(errors="replace")[-50000:])
            for env in container.attrs['Config'].get('Env',[]):
                if env.startswith('OPENEO_TOKEN='): logs=logs.replace(env.split('=',1)[1],'[REDACTED]')
            db.query("UPDATE jobs SET logs=%s WHERE id=%s",(logs,jid))
    # Repair the file status after scheduler/container failures or account cancellation.
    db.query("UPDATE dataset_files f SET status='error',error=COALESCE(j.error,'入库任务已停止'),updated=now() FROM jobs j WHERE f.job_id=j.id AND f.status IN ('queued','processing') AND j.status IN ('error','canceled')")
    for kind,slots in [("batch",1),("script",2),("ingest",1)]:
        if kind in {"batch","ingest"} and db.query("SELECT count(*) AS n FROM jobs WHERE kind IN ('batch','ingest') AND status='running'",one=True)["n"]:
            continue
        count=db.query("SELECT count(*) AS n FROM jobs WHERE kind=%s AND status='running'",(kind,),one=True)["n"]
        for _ in range(max(0,slots-count)):
            with db.connect() as c:
                row=c.execute("SELECT * FROM jobs WHERE kind=%s AND status='queued' ORDER BY created FOR UPDATE SKIP LOCKED LIMIT 1",(kind,)).fetchone()
                if not row: break
                c.execute("UPDATE jobs SET status='running',started=now(),updated=now() WHERE id=%s",(row["id"],))
            try: launch(client,row)
            except Exception as e:
                db.query("UPDATE jobs SET status='error',error=%s,finished=now(),updated=now() WHERE id=%s AND status='running'",(auth.redact(str(e))[:2000],row["id"]))
                try:
                    failed=client.get('gee-'+str(row['id']))
                    if failed.status=='running': failed.stop(timeout=3)
                    for env in failed.attrs.get('Config',{}).get('Env',[]):
                        if env.startswith('OPENEO_TOKEN='): auth.revoke(env.split('=',1)[1])
                    failed.remove()
                except NotFound: pass
                db.query("DELETE FROM tokens WHERE job_id=%s AND scope='script'",(str(row["id"]),))

def main():
    db.init();client=NativeClient()
    # Session advisory lock enforces single scheduler, including after process restarts.
    with db.connect() as lock:
        if not lock.execute("SELECT pg_try_advisory_lock(73409281) AS acquired").fetchone()["acquired"]:
            raise RuntimeError("已有任务调度器运行")
        while True:
            tick(client);time.sleep(2)

if __name__=="__main__": main()
