"""Dataset file management, separate from metadata CRUD and science execution."""
import os
from pathlib import Path
from flask import Blueprint,jsonify,request,g,send_file
from .admin import allowed
from .. import db
from ..services import dataset_files as files
from ..services.administration import fail,audit


def register_file_api(app):
    bp=Blueprint('dataset_files',__name__,url_prefix='/workbench/admin/v1')

    @bp.route('/datasets/<cid>/files',methods=['GET','POST'])
    @allowed('datasets:manage')
    def catalog_files(cid):
        if request.method=='POST':return jsonify({'data':files.create(g.account['user_id'],cid,request.get_json())}),201
        if not db.query('SELECT id FROM collections WHERE id=%s',(cid,),one=True):fail('数据集不存在',404,'AdminNotFound')
        try:
            page=int(request.args.get('page','1'))
            if not 1<=page<=10000:raise ValueError()
        except ValueError:fail('分页参数无效')
        rows=db.query('SELECT * FROM dataset_files WHERE collection_id=%s ORDER BY created DESC LIMIT 51 OFFSET %s',(cid,(page-1)*50))
        total=db.query('SELECT count(*) AS n FROM dataset_files WHERE collection_id=%s',(cid,),one=True)['n']
        return jsonify({'data':[files.public(row) for row in rows[:50]],'has_more':len(rows)>50,'total':total,'page':page,'max_file_size':files.MAX_FILE_SIZE,'chunk_size':files.CHUNK_SIZE})

    @bp.put('/uploads/<fid>/content')
    @allowed('datasets:manage')
    def upload_chunk(fid):
        if request.content_type!='application/octet-stream' or request.content_length is None or not 0<request.content_length<=files.CHUNK_SIZE:fail('上传分块须为有长度的二进制内容，最多 512 KiB')
        try:offset=int(request.headers.get('Upload-Offset',''))
        except ValueError:fail('缺少有效的 Upload-Offset')
        return jsonify(files.append(g.account['user_id'],fid,offset,request.get_data(cache=False)))

    @bp.post('/uploads/<fid>/complete')
    @allowed('datasets:manage')
    def complete(fid):return jsonify({'data':files.complete(g.account['user_id'],fid)})

    @bp.post('/uploads/<fid>/ingest')
    @allowed('datasets:manage')
    def ingest(fid):return jsonify({'data':files.ingest(g.account['user_id'],fid,request.get_json())}),202

    @bp.get('/uploads/<fid>/download')
    @allowed('datasets:manage')
    def download(fid):
        files.uuid_text(fid)
        row=db.query('SELECT * FROM dataset_files WHERE id=%s',(fid,),one=True)
        if not row or row['status'] not in {'stored','queued','processing','ready','error'} or row['received']!=row['size']:fail('完整文件尚不可下载',404,'FileNotFound')
        try:path=files.file_path(fid)
        except ValueError:fail('存储文件不可用',404,'FileNotFound')
        if request.method=='GET':
            with db.connect() as c:audit(c,g.account['user_id'],'file.download.request','dataset_file',fid,{'collection_id':row['collection_id'],'size':row['size'],'sha256':row['sha256']})
        return send_file(path,as_attachment=True,download_name=row['filename'],mimetype='application/octet-stream',etag=row['sha256'],conditional=True)

    @bp.get('/datasets/<cid>/assets')
    @allowed('datasets:manage')
    def assets(cid):
        try:
            page=int(request.args.get('page','1'))
            if not 1<=page<=10000:raise ValueError()
        except ValueError:fail('分页参数无效')
        rows=db.query('''SELECT i.id AS item_id,i.active,i.metadata->'properties'->>'datetime' AS datetime,
            a.key AS band,a.value-'href' AS metadata FROM items i CROSS JOIN LATERAL jsonb_each(i.metadata->'assets') a
            WHERE i.collection_id=%s ORDER BY i.created DESC,i.id,a.key LIMIT 31 OFFSET %s''',(cid,(page-1)*30))
        return jsonify({'data':rows[:30],'has_more':len(rows)>30,'page':page})

    @bp.get('/datasets/<cid>/assets/<iid>/<band>/download')
    @allowed('datasets:manage')
    def download_asset(cid,iid,band):
        row=db.query('SELECT metadata FROM items WHERE collection_id=%s AND id=%s',(cid,iid),one=True)
        asset=(row or {}).get('metadata',{}).get('assets',{}).get(band,{})
        href=asset.get('href','')
        if not isinstance(href,str) or not href.startswith('/data/assets/'):fail('文件不存在',404,'FileNotFound')
        try:path=files.physical(Path(os.environ.get('DATA_ROOT','/data'))/'assets',href.removeprefix('/data/assets/'))
        except (ValueError,OSError):fail('文件不可用',404,'FileNotFound')
        if request.method=='GET':
            with db.connect() as c:audit(c,g.account['user_id'],'asset.download.request','stac_asset',iid+'/'+band,{'collection_id':cid})
        return send_file(path,as_attachment=True,download_name=path.name,mimetype='application/octet-stream',conditional=True)

    app.register_blueprint(bp)
