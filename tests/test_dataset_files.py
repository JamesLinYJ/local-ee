import hashlib,json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from openeo_driver.errors import OpenEOApiException
from gee.services import dataset_files as files


def test_physical_storage_accepts_regular_child_and_rejects_symlinks(tmp_path):
    root=tmp_path/'uploads';root.mkdir();folder=root/'a';folder.mkdir();(folder/'content').write_bytes(b'local')
    assert files.physical(root,'a/content')==folder/'content'
    (folder/'link').symlink_to(folder/'content')
    for name in ['a/link','a/../outside','/absolute','a']:
        with pytest.raises(ValueError):files.physical(root,name)
    (root/'alias').symlink_to(folder,target_is_directory=True)
    with pytest.raises(ValueError):files.physical(root,'alias/content')


@pytest.mark.parametrize('data',[
    {'filename':'../file.tif','size':10,'sha256':'a'*64},
    {'filename':'file.zip','size':10,'sha256':'a'*64},
    {'filename':'file.tif','size':0,'sha256':'a'*64},
    {'filename':'file.tif','size':files.MAX_FILE_SIZE+1,'sha256':'a'*64},
    {'filename':'file.tif','size':10,'sha256':'invalid'},
    {'filename':'file.tif','size':10,'sha256':'a'*64,'path':'/data/assets'},
    {'filename':'\ud800.tif','size':10,'sha256':'a'*64},
    {'filename':'\udfff.csv','size':10,'sha256':'a'*64},
])
def test_upload_validation_precedes_any_database_or_file_access(data):
    with pytest.raises(OpenEOApiException):files.create('synthetic-admin','synthetic-dataset',data)


def test_geotiff_normalization_preserves_mask_scales_offsets_and_order(tmp_path):
    from gee.raster_ingest_runner import run
    source=tmp_path/'source.tif';job=tmp_path/'job';job.mkdir()
    raw=np.array([[[0,2,4],[6,8,10]],[[1,0,3],[4,5,6]]],dtype='int16')
    with rasterio.open(source,'w',driver='GTiff',width=3,height=2,count=2,dtype='int16',nodata=0,crs='EPSG:4326',transform=from_origin(110,30,.01,.01)) as dst:
        dst.write(raw);dst.scales=(.5,2);dst.offsets=(1,-1)
    (job/'ingest.json').write_text(json.dumps({'expected_size':source.stat().st_size,'expected_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'options':{'bands':['red','nir'],'unit':'1','datetime':'2024-01-19T00:00:00Z'}}))
    run(source,job)
    report=json.loads((job/'out/ingest-report.json').read_text())
    assert [b['name'] for b in report['bands']]==['red','nir']
    for index,(scale,offset) in enumerate([(.5,1),(2,-1)]):
        with rasterio.open(job/'out'/f'band-{index+1:02d}.tif') as src:
            actual=src.read(1,masked=True)
            assert np.array_equal(np.ma.getmaskarray(actual),raw[index]==0)
            expected=raw[index]*scale+offset
            assert np.array_equal(actual.compressed(),expected[raw[index]!=0])
            assert src.descriptions==(report['bands'][index]['name'],)
        assert report['bands'][index]['float32_max_absolute_error']==0


def test_worker_uses_native_runtime_after_preparing_job(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4
    from gee import worker
    calls=[]
    monkeypatch.setattr(worker,'prepare',lambda row:calls.append(('prepare',row)))
    client=SimpleNamespace(launch=lambda row:calls.append(('launch',row)) or 'native-task')
    row={'id':str(uuid4()),'kind':'ingest','context':{'upload_id':str(uuid4())}}
    assert worker.launch(client,row)=='native-task'
    assert [x[0] for x in calls]==['prepare','launch']
