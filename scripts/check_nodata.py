import json,time
from pathlib import Path
import openeo,numpy as np,rasterio,requests
root=Path(__file__).resolve().parents[1];base='http://localhost:8787'
pw=next(l.split(': ',1)[1] for l in (root/'deploy/local-login.txt').read_text().splitlines() if l.startswith('Password:'))
c=openeo.connect(base+'/openeo/1.2').authenticate_basic('researcher',pw)
cube=c.load_collection('sentinel-2-l2a',spatial_extent=dict(west=113.55,south=22.30,east=113.57,north=22.32),temporal_extent=['2024-01-19','2024-01-20'],bands=['red'])
mask=cube.apply(lambda x:x==x)
j=cube.mask(mask).save_result('GTiff').create_job(title='验收 · 全部像素掩膜');j.start_job()
for _ in range(90):
 status=j.describe_job()['status']
 if status in ['finished','error','canceled']:break
 time.sleep(2)
r={'job_id':j.job_id,'status':status,'fixture':'real local sample with an all-true mask (not a real all-cloud scene)'}
if status=='finished':
 files=j.get_results().download_files(root/'audit/results/all-masked')
 with rasterio.open(next(p for p in files if p.suffix=='.tif')) as src:
  arr=src.read(1,masked=True);r['valid_pixels']=int(np.count_nonzero(np.isfinite(arr.filled(np.nan))));r['passed']=r['valid_pixels']==0
else:
 logs=str(j.logs());r['logs']=logs;r['passed']=status=='error' and ('NoDataAvailable' in logs or 'Empty' in logs)
(root/'audit/all-masked.json').write_text(json.dumps(r,indent=2));print(r);assert r['passed']
