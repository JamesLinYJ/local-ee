"""File lifecycle controls against a disposable database and trusted generated raster."""
import contextlib,hashlib,io,json,os,secrets,tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import numpy as np,rasterio
from rasterio.transform import from_origin
from gee import auth,db
from gee.migrations import migrate

if not urlsplit(os.environ['DATABASE_URL']).path.removeprefix('/').startswith('gee_admin_check_'):
    raise SystemExit('Disposable database required')
migrate();migrate();db.init()
with tempfile.TemporaryDirectory() as scratch:
    root=Path(scratch);data=root/'data';data.mkdir();uploads=data/'uploads';uploads.mkdir()
    os.environ['DATA_ROOT']=str(data);os.environ['UPLOAD_ROOT']=str(uploads)
    from gee.app import create_app
    from gee.services import local_ingest
    from gee.raster_ingest_runner import run
    name='filecheck_'+uuid4().hex[:10];auth.create_user(name,secrets.token_urlsafe(24),role='admin')
    app=create_app();app.config['TESTING']=True;client=app.test_client();client.set_cookie('gee_session',auth.issue(name))
    origin={'Origin':os.environ.get('PUBLIC_ORIGIN','http://localhost:8787')};base='/workbench/admin/v1';checks=[]
    def expect(response,status,label):
        assert response.status_code==status,(label,response.status_code,response.get_data(as_text=True)[:300])
        checks.append(label);return response
    cid=name+'-raster'
    expect(client.post(base+'/datasets',json={'id':cid,'title':'Generated file validation raster','description':'Synthetic control','license':'proprietary'},headers=origin),201,'create unpublished dataset')
    source=root/'source.tif';raw=np.array([[[0,2,4],[6,8,10]],[[1,0,3],[4,5,6]]],dtype='int16')
    with rasterio.open(source,'w',driver='GTiff',width=3,height=2,count=2,dtype='int16',nodata=0,crs='EPSG:4326',transform=from_origin(110,30,.01,.01)) as dst:
        dst.write(raw);dst.scales=(.5,2);dst.offsets=(1,-1)
    content=source.read_bytes();digest=hashlib.sha256(content).hexdigest()
    init={'filename':'科研影像.tif','size':len(content),'sha256':digest}
    first=expect(client.post(base+'/datasets/'+cid+'/files',json=init,headers=origin),201,'create file upload').json['data'];fid=first['id'];path=base+'/uploads/'+fid
    assert client.post(base+'/datasets/'+cid+'/files',json=init,headers=origin).json['data']['id']==fid
    checks.append('same content reuses persistent upload identity')
    expect(client.post(path+'/complete',json={},headers=origin),409,'incomplete upload cannot complete')
    expect(client.get(path+'/download'),404,'incomplete upload cannot download')
    expect(client.put(path+'/content',data=content[:20],headers={**origin,'Content-Type':'application/octet-stream','Upload-Offset':'1'}),409,'wrong chunk offset rejected')
    expect(client.put(path+'/content',data=content[:20],headers={**origin,'Content-Type':'application/octet-stream','Upload-Offset':'0'}),200,'first chunk committed')
    with (uploads/fid/'content.part').open('ab') as stream:stream.write(b'uncommitted tail')
    expect(client.put(path+'/content',data=content[20:],headers={**origin,'Content-Type':'application/octet-stream','Upload-Offset':'20'}),200,'resume discards only uncommitted tail')
    expect(client.post(path+'/complete',json={},headers=origin),200,'complete verifies size and SHA256')
    result=expect(client.get(path+'/download'),200,'download original bytes')
    assert result.data==content
    assert 'attachment' in result.headers['Content-Disposition'] and 'filename*=' in result.headers['Content-Disposition']
    checks.append('Unicode filename preserved and original download SHA256 identical')
    ranged=expect(client.get(path+'/download',headers={'Range':'bytes=13-30'}),206,'original file supports bounded range download')
    assert ranged.data==content[13:31]
    expect(client.post(path+'/ingest',json={'datetime':'2024-01-19','unit':'1'},headers=origin),400,'ingestion requires explicit timezone')
    queued=expect(client.post(path+'/ingest',json={'datetime':'2024-01-19T00:00:00Z','unit':'1','bands':['red','nir']},headers=origin),202,'queue GeoTIFF ingestion').json['data']
    jid=queued['job_id'];folder=data/'jobs'/jid;(folder/'out').mkdir(parents=True)
    row=db.query('SELECT * FROM jobs WHERE id=%s',(jid,),one=True)
    db.query("UPDATE jobs SET status='running' WHERE id=%s",(jid,))
    local_ingest.prepare(row,folder)
    with contextlib.redirect_stdout(io.StringIO()):run(uploads/fid/'content',folder)
    local_ingest.publish(data,row)
    file=client.get(base+'/datasets/'+cid+'/files').json['data'][0]
    assert file['status']=='ready' and file['item_id']=='upload-'+fid
    checks.append('successful ingestion records immutable STAC item')
    assets=client.get(base+'/datasets/'+cid+'/assets').json['data'];assert {a['band'] for a in assets}=={'red','nir'}
    for index,(band,scale,offset) in enumerate([('red',.5,1),('nir',2,-1)]):
        response=expect(client.get(base+'/datasets/'+cid+'/assets/upload-'+fid+'/'+band+'/download'),200,'download normalized '+band+' COG')
        downloaded=root/(band+'.tif');downloaded.write_bytes(response.data)
        with rasterio.open(downloaded) as src:
            array=src.read(1,masked=True);expected=raw[index]*scale+offset
            assert np.array_equal(np.ma.getmaskarray(array),raw[index]==0)
            assert np.array_equal(array.compressed(),expected[raw[index]!=0])
    checks.append('COG values masks scales offsets and band order match independent NumPy reference')
    assert cid not in {c['id'] for c in client.get('/workbench/catalog').json}
    checks.append('ingestion does not automatically publish the dataset')
    expect(client.patch(base+'/datasets/'+cid,json={'enabled':True,'revision':1},headers=origin),200,'publish only after successful ingestion')
    assert cid in {c['id'] for c in client.get('/workbench/catalog').json}
    member=name+'_member';auth.create_user(member,secrets.token_urlsafe(24))
    other=app.test_client();other.set_cookie('gee_session',auth.issue(member))
    expect(other.get(base+'/datasets/'+cid+'/files'),403,'researcher cannot enter file administration')
    expect(other.get(path+'/download'),403,'researcher cannot fetch administrator original upload')
    wrong=expect(client.post(base+'/datasets/'+cid+'/files',json={**init,'sha256':'0'*64},headers=origin),201,'reserve checksum failure control').json['data']['id']
    expect(client.put(base+'/uploads/'+wrong+'/content',data=content,headers={**origin,'Content-Type':'application/octet-stream','Upload-Offset':'0'}),200,'upload checksum failure control')
    expect(client.post(base+'/uploads/'+wrong+'/complete',json={},headers=origin),409,'incorrect SHA256 never becomes stored or ingested')
    print(json.dumps({'passed':len(checks),'checks':checks,'synthetic_raster':True,'disposable_database':True,'mask_mismatches':0,'max_absolute_error':0.0,'parse_isolation':'This fixture runs in one candidate test container; actual scheduler isolation requires separate runtime readback.'},ensure_ascii=False,indent=2))
