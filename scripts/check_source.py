"""Independent readback of public source DN/quality on the stored sample grid.
Runs in the allowlisted ingestion network; never imports production ingest code.
"""
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling
root=Path('/data');folder=next(p for p in (root/'assets/sentinel-2-l2a').glob('*') if json.loads((p/'source.json').read_text()).get('collection')=='sentinel-2-c1-l2a')
metadata=json.loads((folder/'source.json').read_text());report={'source_id':metadata['id'],'bands':{}}
arrays={}
with rasterio.open(folder/'red.tif') as anchor:
    grid=dict(crs=anchor.crs,transform=anchor.transform,height=anchor.height,width=anchor.width)
for key in ['red','nir','green','scl']:
    asset=metadata['assets'][key]
    with rasterio.open(asset['href']) as raw, WarpedVRT(raw,**grid,resampling=Resampling.nearest) as aligned:
        arrays[key]=aligned.read(1,masked=True).astype('float32').filled(np.nan)
valid=np.isin(arrays['scl'],[4,5,6,7])
for key in ['red','nir','green']:
    rb=metadata['assets'][key]['raster:bands'][0]
    expected=np.where(valid,arrays[key]*rb['scale']+rb['offset'],np.nan)
    with rasterio.open(folder/(key+'.tif')) as src:actual=src.read(1,masked=True).filled(np.nan)
    mask=np.isfinite(actual)&np.isfinite(expected);delta=np.abs(actual[mask]-expected[mask])
    record={'valid_pixels':int(mask.sum()),'mask_mismatches':int(np.sum(np.isfinite(actual)!=np.isfinite(expected))),
            'max_abs_error':float(delta.max(initial=0)),'scale':rb['scale'],'offset':rb['offset']}
    record['passed']=record['mask_mismatches']==0 and record['max_abs_error']<=1e-7
    report['bands'][key]=record
out=root/'reference';out.mkdir(exist_ok=True)
np.savez_compressed(out/'sentinel-source-dn.npz',**arrays)
(out/'source-normalization.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
assert all(r['passed'] for r in report['bands'].values())
