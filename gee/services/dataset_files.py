"""Bounded resumable file storage. No external raster parser runs in the API."""
import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
from uuid import UUID,uuid4
from psycopg.types.json import Jsonb
from .administration import actor_check,audit,fail,fields
from .. import db

CHUNK_SIZE=512*1024
MAX_FILE_SIZE=512*1024**2
TOTAL_RESERVATION=8*1024**3
EXTENSIONS={'.tif','.tiff','.nc','.csv','.geojson','.json'}


def upload_root():
    return Path(os.environ.get('UPLOAD_ROOT','/uploads'))


def physical(root,relative,*,must_exist=True):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Storage root is not a physical directory')
    parts=Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(x in {'.','..',''} for x in parts):raise ValueError('Invalid storage child')
    path=root
    for index,part in enumerate(parts):
        path=path/part
        try:mode=path.lstat().st_mode
        except FileNotFoundError:
            if not must_exist and index==len(parts)-1:return path
            raise ValueError('Stored file is missing') from None
        if stat.S_ISLNK(mode) or (index<len(parts)-1 and not stat.S_ISDIR(mode)):raise ValueError('Invalid physical storage component')
    if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('Storage object is not a regular file')
    return path


def uuid_text(value):
    try:
        result=str(UUID(value))
        if result!=value:raise ValueError()
        return result
    except (ValueError,TypeError,AttributeError):fail('文件 ID 无效',404,'FileNotFound')


def file_path(fid,complete=True):
    return physical(upload_root(),uuid_text(str(fid))+('/content' if complete else '/content.part'))


def sha256_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def public(row):
    keys=('id','collection_id','filename','size','received','sha256','status','created','updated','job_id','item_id','error','options')
    result={key:row.get(key) for key in keys}
    for key in ['id','job_id']:
        if result[key] is not None:result[key]=str(result[key])
    return result


def create(actor,cid,data):
    fields(data,{'filename','size','sha256'})
    name=data.get('filename');size=data.get('size');digest=data.get('sha256')
    if not isinstance(name,str) or not 1<=len(name)<=180 or name in {'.','..'} or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):fail('文件名必须是普通文件名')
    try:name.encode('utf-8')
    except UnicodeEncodeError:fail('文件名必须是有效的 Unicode 文本')
    if Path(name).suffix.lower() not in EXTENSIONS:fail('支持 GeoTIFF、NetCDF、CSV、GeoJSON 和 JSON 文件；不接收压缩包或可执行文件')
    if type(size) is not int or not 0<size<=MAX_FILE_SIZE:fail('单文件大小须在 1 字节至 512 MiB 之间')
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):fail('必须提供文件 SHA-256')
    root=upload_root()
    if root.is_symlink() or not root.is_dir():fail('上传存储未就绪',503,'UploadStorageUnavailable')
    with db.connect() as c:
        c.execute('SELECT pg_advisory_xact_lock(1879645013)')
        actor_check(c,actor,'datasets:manage')
        if not c.execute('SELECT id FROM collections WHERE id=%s FOR SHARE',(cid,)).fetchone():fail('数据集不存在',404,'AdminNotFound')
        existing=c.execute('SELECT * FROM dataset_files WHERE collection_id=%s AND sha256=%s AND size=%s',(cid,digest,size)).fetchone()
        if existing:
            if existing['status']=='canceled':fail('同内容上传已取消，请由管理员恢复或清理',409,'UploadCanceled')
            return public(existing)
        if c.execute('SELECT count(*) AS n FROM dataset_files').fetchone()['n']>=2048 or c.execute('SELECT count(*) AS n FROM dataset_files WHERE collection_id=%s',(cid,)).fetchone()['n']>=500:fail('文件数量达到上限（每数据集 500，全局 2048）',429,'UploadQuotaExceeded')
        if c.execute("SELECT count(*) AS n FROM dataset_files WHERE user_id=%s AND status='uploading'",(actor,)).fetchone()['n']>=2:fail('最多同时保留 2 个未完成上传',429,'UploadQuotaExceeded')
        if c.execute('SELECT COALESCE(sum(size),0) AS n FROM dataset_files').fetchone()['n']+size>TOTAL_RESERVATION:fail('上传暂存总配额为 8 GiB',429,'UploadQuotaExceeded')
        if shutil.disk_usage(root).free<size+1024**3:fail('上传存储剩余空间不足',507,'UploadStorageFull')
        fid=str(uuid4());folder=root/fid;folder.mkdir(mode=0o700)
        try:
            with (folder/'content.part').open('xb'):pass
            row=c.execute('''INSERT INTO dataset_files(id,collection_id,user_id,filename,size,sha256)
                VALUES(%s,%s,%s,%s,%s,%s) RETURNING *''',(fid,cid,actor,name,size,digest)).fetchone()
            audit(c,actor,'file.create','dataset_file',fid,{'collection_id':cid,'filename':name,'size':size,'sha256':digest})
        except BaseException:
            # Only this request's exclusive folder, before commit is attempted.
            (folder/'content.part').unlink(missing_ok=True)
            folder.rmdir()
            raise
    return public(row)


def append(actor,fid,offset,body):
    uuid_text(fid)
    if type(offset) is not int or offset<0 or not body or len(body)>CHUNK_SIZE:fail('上传分块或偏移无效')
    with db.connect() as c:
        actor_check(c,actor,'datasets:manage')
        row=c.execute('SELECT * FROM dataset_files WHERE id=%s FOR UPDATE',(fid,)).fetchone()
        if not row:fail('文件不存在',404,'FileNotFound')
        if row['status']!='uploading' or row['received']!=offset:fail('上传偏移或状态已变化，请重新选择同一文件继续',409,'UploadOffsetConflict')
        if offset+len(body)>row['size']:fail('分块超出声明文件大小')
        path=file_path(fid,False)
        if shutil.disk_usage(path.parent).free<len(body)+1024**3:fail('上传存储剩余空间不足',507,'UploadStorageFull')
        with path.open('r+b') as stream:
            if os.fstat(stream.fileno()).st_size<offset:fail('暂存文件与上传记录不一致',409,'UploadStorageConflict')
            # Discard only an uncommitted tail left by a process restart.
            stream.truncate(offset);stream.seek(offset);stream.write(body);stream.flush();os.fsync(stream.fileno())
        c.execute('UPDATE dataset_files SET received=%s,updated=now() WHERE id=%s',(offset+len(body),fid))
    return {'received':offset+len(body)}


def complete(actor,fid):
    uuid_text(fid)
    with db.connect() as c:
        actor_check(c,actor,'datasets:manage')
        row=c.execute('SELECT * FROM dataset_files WHERE id=%s FOR UPDATE',(fid,)).fetchone()
        if not row:fail('文件不存在',404,'FileNotFound')
        if row['status'] in {'stored','queued','processing','ready'}:return public(row)
        if row['status']!='uploading' or row['received']!=row['size']:fail('文件尚未上传完整',409,'UploadIncomplete')
        try:path=file_path(fid,False)
        except ValueError:path=file_path(fid)
        if path.stat().st_size!=row['size'] or sha256_file(path)!=row['sha256']:fail('文件校验失败，请取消后重新上传',409,'UploadChecksumMismatch')
        target=path.with_name('content')
        if path!=target:path.rename(target)
        c.execute("UPDATE dataset_files SET status='stored',updated=now() WHERE id=%s",(fid,))
        audit(c,actor,'file.complete','dataset_file',fid,{'sha256':row['sha256'],'size':row['size']})
        row={**row,'status':'stored'}
    return public(row)


def ingest(actor,fid,options):
    from datetime import datetime,timezone
    fields(options,{'datetime','unit','bands'})
    try:
        date=datetime.fromisoformat(options['datetime'].replace('Z','+00:00'))
        if date.tzinfo is None:raise ValueError()
        date=date.astimezone(timezone.utc).isoformat()
    except (ValueError,KeyError,TypeError,AttributeError):fail('观测时间须带时区，例如 2024-01-19T00:00:00Z')
    unit=options.get('unit');bands=options.get('bands',[])
    if not isinstance(unit,str) or not unit.strip() or len(unit)>64 or any(ord(c)<32 for c in unit):fail('必须明确波段的物理单位')
    if not isinstance(bands,list) or len(bands)>32 or len(set(b for b in bands if isinstance(b,str)))!=len(bands) or any(not isinstance(b,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,63}',b) for b in bands):fail('波段名必须唯一且只含字母、数字和 ._-，最多 32 个')
    uuid_text(fid)
    with db.connect() as c:
        c.execute('SELECT pg_advisory_xact_lock(1879645014)')
        actor_check(c,actor,'datasets:manage')
        row=c.execute('SELECT * FROM dataset_files WHERE id=%s FOR UPDATE',(fid,)).fetchone()
        if not row:fail('文件不存在',404,'FileNotFound')
        if row['status'] not in {'stored','error'}:fail('文件当前不能再次入库',409,'FileNotIngestable')
        if Path(row['filename']).suffix.lower() not in {'.tif','.tiff'}:fail('当前计算入库支持 GeoTIFF；其他格式可先存储和下载',422,'FileFormatNotIngestable')
        source=file_path(fid)
        if shutil.disk_usage(source.parent).free<2*1024**3:fail('入库需保留至少 2 GiB 空间用于标准化输出和安全余量',507,'UploadStorageFull')
        if c.execute("SELECT count(*) AS n FROM jobs WHERE kind='ingest' AND status IN ('queued','running')").fetchone()['n']>=20 or c.execute("SELECT count(*) AS n FROM jobs WHERE kind='ingest' AND user_id=%s AND status IN ('queued','running')",(actor,)).fetchone()['n']>=5:fail('入库任务排队达到上限（每用户 5，全局 20）',429,'UploadQuotaExceeded')
        jid=str(uuid4());opts={'datetime':date,'unit':unit.strip(),'bands':bands}
        c.execute("INSERT INTO jobs(id,user_id,kind,title,status,context) VALUES(%s,%s,'ingest',%s,'queued',%s)",(jid,actor,'入库 · '+row['filename'],Jsonb({'upload_id':fid,'collection_id':row['collection_id'],'options':opts})))
        c.execute("UPDATE dataset_files SET status='queued',job_id=%s,error=NULL,options=%s,updated=now() WHERE id=%s",(jid,Jsonb(opts),fid))
        audit(c,actor,'file.ingest','dataset_file',fid,{'job_id':jid,'options':opts})
    return {'job_id':jid,'status':'queued'}
