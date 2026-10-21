"""Real local API/GeoTrellis acceptance and independent NumPy comparison."""
import json,time,os
from pathlib import Path
import numpy as np
import openeo
import rasterio
from rasterio.warp import reproject,Resampling
from rasterio.features import geometry_mask
import requests
ROOT=Path(__file__).resolve().parents[1];AUDIT=Path(os.environ['GEE_AUDIT_DIR']);AUDIT.mkdir(parents=True,exist_ok=False);BASE='http://localhost:8787';report=[]
login=dict(l.split(': ',1) for l in (ROOT/'deploy/native-login.txt').read_text().splitlines());password=login['Password'];username=login['Username']
s=requests.Session();s.headers['Origin']=BASE
s.post(BASE+'/workbench/login',json={'username':username,'password':password}).raise_for_status()
c=openeo.connect(BASE+'/openeo/1.2').authenticate_basic(username,password)
aoi=dict(west=113.55,south=22.30,east=113.57,north=22.32)
polygon={'type':'Polygon','coordinates':[[[113.55,22.30],[113.57,22.30],[113.57,22.32],[113.55,22.32],[113.55,22.30]]]}
def load(bands,dates=['2024-01-19','2024-01-20']):return c.load_collection('sentinel-2-l2a',spatial_extent=aoi,temporal_extent=dates,bands=bands)
def submit(name,cube,fmt):
    job=cube.save_result(fmt).create_job(title='验收 · '+name);job.start_job();return job
cube=load(['green','red','nir'])
jobs=[('NDVI',submit('NDVI',cube.ndvi(nir='nir',red='red').mean_time(),'GTiff')),
      ('NDWI',submit('NDWI',(cube.band('green')-cube.band('nir'))/(cube.band('green')+cube.band('nir')),'GTiff')),
      ('NetCDF',submit('NetCDF',load(['red','nir']),'NetCDF')),
      ('CSV',submit('区域均值 CSV',load(['red','nir']).aggregate_spatial(polygon,'mean'),'CSV')),
      ('empty',submit('空时间范围',load(['red'],['1990-01-01','1990-01-02']),'GTiff'))]
for name,job in jobs:
    until=time.time()+240
    while time.time()<until:
        meta=job.describe_job()
        if meta['status'] in {'finished','error','canceled'}:break
        time.sleep(2)
    record={'test':name,'job_id':job.job_id,'status':meta['status']}
    log=s.get(BASE+f'/workbench/jobs/{job.job_id}/logs').json()
    (AUDIT/('engine-'+name+'.log')).write_text(log['logs'])
    if name=='empty':record['passed']=meta['status']=='error';report.append(record);continue
    record['passed']=meta['status']=='finished'
    if meta['status']=='finished':
        files=job.get_results().download_files(AUDIT/'results'/name)
        record['files']=[p.name for p in files]
    report.append(record)
    print(record,flush=True)
# Compare raster values on exactly the output CRS/transform/grid.
source=next(p for p in (ROOT/'data/assets/sentinel-2-l2a').glob('*') if json.loads((p/'source.json').read_text()).get('collection')=='sentinel-2-c1-l2a')
for name,left,right in [('NDVI','nir','red'),('NDWI','green','nir')]:
    record=next(r for r in report if r['test']==name)
    if not record['passed']:continue
    f=next((AUDIT/'results'/name).glob('*.tif'))
    with rasterio.open(f) as output:
        actual=output.read(1);bands={}
        for b in [left,right]:
            with rasterio.open(source/(b+'.tif')) as src:
                target=np.full(output.shape,np.nan,dtype='float32')
                reproject(rasterio.band(src,1),target,src_transform=src.transform,src_crs=src.crs,dst_transform=output.transform,dst_crs=output.crs,dst_nodata=np.nan,resampling=Resampling.nearest)
                bands[b]=target
        with np.errstate(divide='ignore',invalid='ignore'):expected=(bands[left]-bands[right])/(bands[left]+bands[right])
        valid=np.isfinite(expected)&np.isfinite(actual);error=np.abs(actual[valid]-expected[valid])
        record.update(valid_pixels=int(valid.sum()),mask_mismatches=int(np.sum(np.isfinite(actual)!=np.isfinite(expected))),max_abs_error=float(error.max(initial=0)),crs=str(output.crs),shape=list(output.shape))
        record['passed']=record['mask_mismatches']==0 and np.allclose(actual[valid],expected[valid],rtol=1e-6,atol=1e-6)
(AUDIT/'engine-integration.json').write_text(json.dumps(report,indent=2,default=bool));print(json.dumps(report,indent=2,default=bool))
assert all(r['passed'] for r in report),report
