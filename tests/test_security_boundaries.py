"""Defensive structure/path tests using only disposable synthetic fixtures."""
from pathlib import Path
from uuid import uuid4
import pytest
from gee.graph import validate
from gee.artifacts import artifact_path,output_dir

@pytest.mark.parametrize('value',[{'node':1},{'process_id':'mean'},{'callback':{}},{'process_graph':{'a':{'process_id':'mean','arguments':{'data':[1]},'result':True}},'extra':1},{'from_parameter':'x','extra':1},{'from_node':'a','extra':1}])
def test_argument_representations_are_atomic(value):
    graph={'a':{'process_id':'mean','arguments':{'data':[1]}},'out':{'process_id':'save_result','arguments':{'data':value,'format':'GTiff'},'result':True}}
    with pytest.raises(ValueError):validate(graph)

def test_supported_callback_and_geometry_remain_valid():
    validate({'a':{'process_id':'apply','arguments':{'data':[1,2],'process':{'process_graph':{'m':{'process_id':'multiply','arguments':{'x':{'from_parameter':'x'},'y':2},'result':True}}}},'result':True}})
    validate({'a':{'process_id':'aggregate_spatial','arguments':{'data':[1],'geometries':{'type':'Point','coordinates':[0,0]},'reducer':{'process_graph':{'m':{'process_id':'mean','arguments':{'data':{'from_parameter':'data'}},'result':True}}}},'result':True}})

def output_fixture(tmp_path):
    jid=str(uuid4());out=tmp_path/'jobs'/jid/'out';out.mkdir(parents=True);(out/'result.csv').write_text('value\n1\n');return jid,out

def test_regular_output_is_accepted(tmp_path):
    jid,out=output_fixture(tmp_path)
    assert artifact_path(tmp_path,jid,'result.csv')==out/'result.csv'

@pytest.mark.parametrize('component',['out','job','file'])
def test_symlink_components_are_rejected(tmp_path,component):
    jid,out=output_fixture(tmp_path)
    if component=='out':
        out.rename(out.with_name('saved'));out.symlink_to(out.with_name('saved'),target_is_directory=True)
    elif component=='job':
        job=out.parent;job.rename(job.with_name('saved'));job.symlink_to(job.with_name('saved'),target_is_directory=True)
    else:
        (out/'result.csv').rename(out/'saved.csv');(out/'result.csv').symlink_to(out/'saved.csv')
    with pytest.raises(ValueError):artifact_path(tmp_path,jid,'result.csv')

@pytest.mark.parametrize('name',['../result.csv','/tmp/result.csv','.','..'])
def test_non_child_names_are_rejected(tmp_path,name):
    jid,_=output_fixture(tmp_path)
    with pytest.raises(ValueError):artifact_path(tmp_path,jid,name)

def test_external_optical_driver_accepts_tiff_and_rejects_other_format(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from gee.ingest import open_optical_asset
    values=np.ones((2,2),dtype="uint8")
    for driver,suffix in [("GTiff","tif"),("PNG","png")]:
        path=tmp_path/("sample."+suffix)
        with rasterio.open(path,"w",driver=driver,width=2,height=2,count=1,dtype="uint8",transform=from_origin(0,2,1,1)) as dst:dst.write(values,1)
        if driver=="GTiff":
            with open_optical_asset(path) as src:assert np.array_equal(src.read(1),values)
        else:
            with pytest.raises(rasterio.errors.RasterioIOError):open_optical_asset(path)

class JsonResponse:
    is_redirect=False
    def __init__(self,chunks,length=None):
        self.chunks=chunks;self.headers={} if length is None else {'Content-Length':str(length)};self.closed=False
    def raise_for_status(self):pass
    def iter_content(self,size):yield from self.chunks
    def close(self):self.closed=True

@pytest.mark.parametrize('chunks,length', [([b'12345'],None),([b'{}'],10),([b'12',b'345'],None)])
def test_provider_json_byte_limits(chunks,length):
    from gee.sync import response_json
    response=JsonResponse(chunks,length)
    with pytest.raises(ValueError,match='byte limit'):response_json(response,max_bytes=4)
    assert response.closed

def test_provider_json_legitimate_control():
    from gee.sync import response_json
    response=JsonResponse([b'{"features":',b'[]}'])
    assert response_json(response)=={'features':[]}
    assert response.closed

def test_all_password_verification_uses_shared_limit(monkeypatch):
    from flask import Flask
    from werkzeug.exceptions import TooManyRequests
    from gee import auth
    app=Flask(__name__);calls=[]
    monkeypatch.setattr(auth,'reserve_auth_attempt',lambda name,source:calls.append((name,source)) or False)
    with app.test_request_context('/openeo/credentials/basic',environ_base={'REMOTE_ADDR':'127.0.0.1'}):
        with pytest.raises(TooManyRequests):auth.verify('synthetic-user','synthetic-input')
    assert calls==[('synthetic-user','127.0.0.1')]


def test_node_description_remains_supported():
    validate({'a':{'process_id':'mean','arguments':{'data':[1]},'description':'User note','namespace':None,'result':True}})
    with pytest.raises(ValueError):validate({'a':{'process_id':'mean','description':{},'result':True}})


def test_ingestion_disk_budget_and_low_watermark(monkeypatch,tmp_path):
    from gee import ingest
    from types import SimpleNamespace
    monkeypatch.setattr(ingest.shutil,'disk_usage',lambda path:SimpleNamespace(free=100))
    budget=ingest.IngestBudget(tmp_path,max_bytes=20,min_free=10)
    budget.reserve(10)
    with pytest.raises(ValueError,match='budget'):budget.reserve(11)
    low=ingest.IngestBudget(tmp_path,max_bytes=200,min_free=95)
    with pytest.raises(ValueError,match='free space'):low.reserve(10)


def test_ingestion_low_watermark_uses_actual_output_mount(monkeypatch,tmp_path):
    from gee import ingest
    from types import SimpleNamespace
    target=tmp_path/'assets';target.mkdir()
    seen=[]
    def usage(path):
        seen.append(Path(path))
        return SimpleNamespace(free=5 if Path(path)==target else 1000)
    monkeypatch.setattr(ingest.shutil,'disk_usage',usage)
    budget=ingest.IngestBudget(tmp_path,max_bytes=200,min_free=10)
    with pytest.raises(ValueError,match='free space'):budget.reserve(1,target=target/'new-item')
    assert seen==[target]
