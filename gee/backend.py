import json
import os
import uuid
from pathlib import Path
from psycopg.types.json import Jsonb
from openeo_driver.backend import (BatchJobs, BatchJobMetadata, JobListing,
    CollectionCatalog, Processing, OpenEoBackendImplementation, UdfRuntimes)
from openeo_driver.config import OpenEoBackendConfig
from openeo_driver.processes import ProcessRegistry
from openeo_driver.errors import OpenEOApiException, JobNotFinishedException
from . import db, graph, auth
from .artifacts import artifact_path

DATA = Path(os.environ.get("DATA_ROOT", "/data"))

class Catalog(CollectionCatalog):
    def __init__(self): super().__init__([])
    def get_all_metadata(self):
        return [r["metadata"] for r in db.query("SELECT metadata || managed_metadata AS metadata FROM collections WHERE enabled ORDER BY id")]
    def get_collection_metadata(self, collection_id):
        self._catalog = {m["id"]: m for m in self.get_all_metadata()}
        return super().get_collection_metadata(collection_id)
    def get_collection_items(self, collection_id, parameters):
        self.get_collection_metadata(collection_id)
        items = db.query("SELECT metadata FROM items WHERE collection_id=%s AND active ORDER BY id LIMIT 1000", (collection_id,))
        # Public catalog metadata never exposes local filesystem paths.
        features = []
        for row in items:
            item = row["metadata"]
            from flask import request
            from urllib.parse import quote
            item["assets"] = {k: {**{x:v for x,v in a.items() if x != "href"},
                "href":request.url_root.rstrip('/')+'/workbench/catalog/'+quote(item['id'],safe='')+'/assets/'+quote(k,safe='')} for k,a in item["assets"].items()}
            features.append(item)
        return {"type": "FeatureCollection", "features": features, "links": []}

class Jobs(BatchJobs):
    def create_job(self, *, user, process, api_version, metadata, job_options=None):
        try: graph.validate(process.get("process_graph"))
        except (ValueError, TypeError) as e:
            raise OpenEOApiException(str(e), code="ProcessGraphInvalid", status_code=400)
        if job_options:
            raise OpenEOApiException("首版资源限额由管理员统一配置", code="JobOptionsInvalid", status_code=400)
        # Freeze all referenced collection metadata and item versions in one transaction.
        ids = set()
        def scan(v):
            if isinstance(v, dict):
                if v.get("process_id") == "load_collection":
                    cid = v.get("arguments", {}).get("id")
                    if not isinstance(cid, str): raise ValueError("数据集 id 必须是字符串")
                    ids.add(cid)
                for x in v.values(): scan(x)
            elif isinstance(v,list):
                for x in v: scan(x)
        try: scan(process)
        except ValueError as e: raise OpenEOApiException(str(e), code="ProcessGraphInvalid", status_code=400)
        with db.connect() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            c.execute("SELECT id FROM users WHERE id=%s FOR UPDATE",(user.user_id,))
            internal=user.internal_auth_data or {}
            parent=internal.get('job_id') if internal.get('scope')=='script' else None
            context={}
            if parent:
                if not c.execute("SELECT id FROM jobs WHERE id=%s AND user_id=%s AND kind='script' AND status='running' FOR SHARE",(parent,user.user_id)).fetchone():
                    raise OpenEOApiException('脚本已停止，请重新运行',code='ScriptNotRunning',status_code=409)
                context={'source_job_id':str(parent)}
            if c.execute("SELECT count(*) AS n FROM jobs WHERE user_id=%s AND status IN ('created','queued','running')", (user.user_id,)).fetchone()["n"] >= 30:
                raise OpenEOApiException("待处理任务上限为 30", code="QuotaExceeded", status_code=429)
            snapshot = {}
            for cid in ids:
                row = c.execute("SELECT metadata || managed_metadata AS metadata FROM collections WHERE id=%s AND enabled", (cid,)).fetchone()
                if not row: raise OpenEOApiException(f"数据集未入库: {cid}", code="CollectionNotFound", status_code=404)
                items = [r["metadata"] for r in c.execute("SELECT metadata FROM items WHERE collection_id=%s AND active ORDER BY id", (cid,))]
                snapshot[cid] = {"collection": row["metadata"], "items": items}
            jid = str(uuid.uuid4())
            c.execute("INSERT INTO jobs(id,user_id,kind,title,status,process,snapshot,context) VALUES(%s,%s,'batch',%s,'created',%s,%s,%s)",
                (jid, user.user_id, str(metadata.get("title") or "未命名任务")[:200], Jsonb(process), Jsonb(snapshot),Jsonb(context)))
        return self.get_job_info(jid, user.user_id)

    @staticmethod
    def metadata(row):
        return BatchJobMetadata(**{k:row[k] for k in ("id","status","created","process","title","updated","started","finished")})._replace(id=str(row["id"]))
    def get_job_info(self, job_id, user_id): return self.metadata(db.job(job_id, user_id))
    def get_user_jobs(self, user_id, limit=None, request_parameters=None):
        return JobListing([self.metadata(r) for r in db.query("SELECT * FROM jobs WHERE user_id=%s AND kind='batch' ORDER BY created DESC LIMIT %s", (user_id, min(limit or 100,1000)))], next_parameters=None)
    def start_job(self, job_id, user):
        row = db.job(job_id, user.user_id)
        if row["status"] not in {"created", "queued", "running"}:
            raise OpenEOApiException("结束的任务请使用重新提交以保留原结果", code="JobNotStartable", status_code=409)
        db.query("UPDATE jobs SET status='queued',updated=now() WHERE id=%s AND status='created'", (job_id,))
    def get_result_assets(self, job_id, user_id):
        row = db.job(job_id,user_id)
        if row["status"] != "finished": raise JobNotFinishedException()
        assets={}
        try:
            for name,m in row["assets"].items():
                path=artifact_path(DATA,job_id,name)
                assets[name]={**m,"output_dir":str(path.parent),"href":str(path)}
        except (ValueError,OSError):
            raise OpenEOApiException("结果文件不可用",code="JobAssetNotFound",status_code=404)
        return assets
    def get_log_entries(self, job_id, *, user_id, offset=None, limit=None, level="debug"):
        row=db.job(job_id,user_id)
        start=int(offset or 0)
        return [{"id":str(i),"level":"info","message":line} for i,line in enumerate(row["logs"].splitlines()) if i>=start][:min(int(limit or 200),2000)]
    def cancel_job(self, job_id, user_id):
        db.job(job_id,user_id)
        db.query("UPDATE jobs SET status='canceled',updated=now(),finished=now() WHERE id=%s AND status IN ('created','queued','running')", (job_id,))
    def delete_job(self, job_id, user_id):
        row=db.job(job_id,user_id)
        if row["status"] in {"queued","running"}:
            raise OpenEOApiException("先取消运行中的任务",code="JobLocked",status_code=409)
        db.query("DELETE FROM jobs WHERE id=%s",(job_id,))

class Processes(Processing):
    def get_process_registry(self, api_version):
        registry=ProcessRegistry()
        from openeo_driver.specs import SPECS_ROOT
        for name in sorted(graph.SUPPORTED):
            if name in graph.LOCAL_PROCESSES:
                from .local_processes import process_spec
                registry.add_spec(process_spec(name))
                continue
            path=SPECS_ROOT/'openeo-processes/1.x'/f'{name}.json'
            if not path.exists(): path=SPECS_ROOT/'openeo-processes/1.x/proposals'/f'{name}.json'
            spec=json.loads(path.read_text())
            if name=='load_collection':
                spec['parameters'].append({'name':'_gee_item_ids','description':'Local EE adapter: exact immutable item selection, checked against the job snapshot.','optional':True,'schema':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':1000}})
            registry.add_spec(spec)
        return registry
    def validate(self, process_graph, env=None):
        try: graph.validate(process_graph)
        except ValueError as e: return [{"code":"ProcessGraphInvalid","message":str(e)}]
        return []
    def evaluate(self, process_graph, env=None):
        raise OpenEOApiException("请创建批处理任务",code="FeatureUnsupported",status_code=501)

class Backend(OpenEoBackendImplementation):
    def __init__(self):
        config=OpenEoBackendConfig(id="private-gee",capabilities_title="私有遥感工作台",
            capabilities_description="仅使用本地数据的 GeoTrellis 批处理服务",
            enable_basic_auth=True, valid_basic_auth=auth.verify, enable_oidc_auth=False, oidc_providers=[],
            capabilities_backend_version="0.1.0", processing_facility="Local", processing_software="private-gee")
        # Upstream views also read the process-global getter, not only backend.config.
        from openeo_driver.config.load import _backend_config_getter
        _backend_config_getter._config=config
        super().__init__(catalog=Catalog(),batch_jobs=Jobs(),processing=Processes(),config=config,
                         udf_runtimes=UdfRuntimes(), conformance_classes=["https://api.openeo.org/1.2.0"])
    def file_formats(self):
        return {"input":{},"output":{k:{"title":k,"gis_data_types":t,"parameters":{}} for k,t in [("GTiff",["raster"]),("NetCDF",["raster"]),("CSV",["vector"])]}}
    def postprocess_capabilities(self, capabilities):
        capabilities["endpoints"]=[e for e in capabilities.get("endpoints",[]) if e["path"] not in {"/result","/udf_runtimes"}]
        # Upstream's default links are policies of a different hosted service.
        from flask import request
        capabilities['links']=[l for l in capabilities.get('links',[]) if l.get('href','').startswith(request.url_root)]
        return capabilities
