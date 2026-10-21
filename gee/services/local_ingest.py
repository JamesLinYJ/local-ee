"""Trusted ingestion publication; all external-format parsing stays in the sandbox."""
import json,math,os,shutil
from pathlib import Path
from psycopg.types.json import Jsonb
from .dataset_files import file_path,sha256_file,physical
from .administration import audit
from .. import db
from ..artifacts import artifact_path


def prepare(row,folder):
    fid=row['context']['upload_id']
    with db.connect() as c:
        upload=c.execute('SELECT * FROM dataset_files WHERE id=%s FOR UPDATE',(fid,)).fetchone()
        if not upload or str(upload['job_id'])!=str(row['id']) or upload['status']!='queued':raise ValueError('入库文件状态已变化')
        source=file_path(fid)
        config={'options':upload['options'],'expected_size':upload['size'],'expected_sha256':upload['sha256']}
        (folder/'ingest.json').write_text(json.dumps(config))
        c.execute("UPDATE dataset_files SET status='processing',updated=now() WHERE id=%s",(fid,))
    return source


def publish(root,row):
    from ..ingest import collection_metadata,register,IngestBudget
    fid=row['context']['upload_id'];jid=str(row['id'])
    path=artifact_path(root,jid,'ingest-report.json')
    if path.stat().st_size>65536:raise ValueError('入库报告过大')
    report=json.loads(path.read_text());bands=report.get('bands');bbox=report.get('bbox')
    import re
    if not isinstance(bands,list) or not 1<=len(bands)<=32 or any(not isinstance(b,dict) or not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,63}',b.get('name','')) for b in bands):raise ValueError('入库波段报告无效')
    names=[b['name'] for b in bands]
    if len(set(names))!=len(names) or not isinstance(bbox,list) or len(bbox)!=4 or any(type(x) not in {int,float} or not math.isfinite(x) for x in bbox) or not (-180<=bbox[0]<bbox[2]<=180 and -90<=bbox[1]<bbox[3]<=90):raise ValueError('入库地理范围或波段无效')
    sources=[]
    for index,band in enumerate(bands):
        expected=f'band-{index+1:02d}.tif'
        if band.get('filename')!=expected:raise ValueError('入库输出文件名无效')
        sources.append(artifact_path(root,jid,expected))
    if sum(p.stat().st_size for p in sources)>512*1024**2:raise ValueError('入库输出超过 512 MiB')
    with db.connect() as c:
        upload=c.execute('SELECT * FROM dataset_files WHERE id=%s FOR UPDATE',(fid,)).fetchone()
        job=c.execute('SELECT status FROM jobs WHERE id=%s FOR UPDATE',(jid,)).fetchone()
        if not upload or upload['status']!='processing' or str(upload['job_id'])!=jid or not job or job['status']!='running':raise ValueError('入库已停止，未发布数据')
        if report.get('source_sha256')!=upload['sha256']:raise ValueError('入库报告来源不符')
        cid=upload['collection_id'];options=upload['options'];units={name:options['unit'] for name in names}
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',cid):raise ValueError('数据集 ID 无效')
        collection=c.execute('SELECT metadata FROM collections WHERE id=%s',(cid,)).fetchone()['metadata']
        old_names=collection.get('cube:dimensions',{}).get('bands',{}).get('values',[])
        if old_names and (old_names!=names or collection.get('gee:units')!=units):raise ValueError('新影像的波段或单位与数据集不一致，请创建单独的数据集')
        item_id='upload-'+fid
        base=Path(root)/'assets';base.mkdir(exist_ok=True)
        if base.is_symlink():raise ValueError('资产根目录无效')
        dataset=base/cid
        if dataset.is_symlink():raise ValueError('数据集目录无效')
        dataset.mkdir(exist_ok=True)
        destination=dataset/item_id
        if destination.is_symlink():raise ValueError('影像目录无效')
        destination.mkdir(exist_ok=True)
        assets={}
        for index,source in enumerate(sources):
            target=destination/f'band-{index+1:02d}.tif'
            if target.exists():
                physical(base,str(target.relative_to(base)))
                if sha256_file(source)!=sha256_file(target):raise ValueError('既有入库版本内容不同，拒绝覆盖')
            else:shutil.copyfile(source,target)
            target.chmod(0o640)
            name=names[index]
            assets[name]={'href':'/data/assets/'+str(target.relative_to(base)),'type':'image/tiff; application=geotiff; profile=cloud-optimized','roles':['data'],'file:size':target.stat().st_size,'file:checksum':'sha256:'+sha256_file(target),'raster:bands':[{'data_type':'float32','nodata':'nan','unit':units[name]}]}
        timestamp=options['datetime']
        meta=collection_metadata(cid,collection.get('title',cid),names,bbox,[timestamp,timestamp],units)
        item={'type':'Feature','stac_version':'1.0.0','id':item_id,'collection':cid,'bbox':bbox,
            'geometry':{'type':'Polygon','coordinates':[[[bbox[0],bbox[1]],[bbox[2],bbox[1]],[bbox[2],bbox[3]],[bbox[0],bbox[3]],[bbox[0],bbox[1]]]]},
            'properties':{'datetime':timestamp,'gee:upload_id':fid,'gee:source_sha256':upload['sha256'],'gee:source_filename':upload['filename'],'gee:processing':report},'assets':assets,'links':[]}
        # register owns its own catalog transaction. Collection stays unpublished if it was a draft.
        register(cid,meta,item,budget=IngestBudget())
        c.execute("UPDATE dataset_files SET status='ready',item_id=%s,error=NULL,updated=now() WHERE id=%s",(item_id,fid))
        c.execute("UPDATE jobs SET status='finished',finished=now(),updated=now() WHERE id=%s",(jid,))
        audit(c,upload['user_id'],'file.ready','dataset_file',fid,{'item_id':item_id,'bands':names,'sha256':upload['sha256']})
