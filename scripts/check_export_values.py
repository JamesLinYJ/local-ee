"""Check exported NetCDF cells and polygon CSV means against independent rasterio/NumPy."""
import csv,json,os
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import reproject,Resampling,transform_geom
from rasterio.features import geometry_mask
from affine import Affine
from netCDF4 import Dataset,num2date
root=Path(__file__).resolve().parents[1]
audit=Path(os.environ.get('GEE_AUDIT_DIR',str(root/'audit')))
source=next(p for p in (root/'data/assets/sentinel-2-l2a').glob('*') if json.loads((p/'source.json').read_text()).get('collection')=='sentinel-2-c1-l2a')
report={};bands={}
with Dataset(audit/'results/NetCDF/openEO.nc') as nc:
 x=np.asarray(nc['x'][:]);y=np.asarray(nc['y'][:]);transform=Affine(x[1]-x[0],0,x[0]-(x[1]-x[0])/2,0,y[1]-y[0],y[0]-(y[1]-y[0])/2)
 crs=rasterio.crs.CRS.from_wkt(nc['crs'].spatial_ref);shape=(len(y),len(x))
 for b in ['red','nir']:
  with rasterio.open(source/(b+'.tif')) as src:
   expected=np.full(shape,np.nan,dtype='float32');reproject(rasterio.band(src,1),expected,src_transform=src.transform,src_crs=src.crs,dst_transform=transform,dst_crs=crs,dst_nodata=np.nan,resampling=Resampling.nearest)
  actual=np.ma.filled(nc[b][0],np.nan);valid=np.isfinite(expected)&np.isfinite(actual);error=np.abs(actual[valid]-expected[valid]);bands[b]=expected
  report['NetCDF_'+b]={'max_abs_error':float(error.max(initial=0)),'mask_mismatches':int(np.sum(np.isfinite(actual)!=np.isfinite(expected))),'passed':bool(np.allclose(actual,expected,equal_nan=True))}
 report['time']={'date':str(num2date(nc['t'][0],nc['t'].units)),'passed':str(num2date(nc['t'][0],nc['t'].units)).startswith('2024-01-19')}
poly={'type':'Polygon','coordinates':[[[113.55,22.30],[113.57,22.30],[113.57,22.32],[113.55,22.32],[113.55,22.30]]]}
mask=geometry_mask([transform_geom('EPSG:4326',crs,poly)],shape,transform,invert=True)
row=next(csv.DictReader((audit/'results/CSV/timeseries.csv').open()))
for b in ['red','nir']:
 expected=float(np.mean(bands[b][mask & np.isfinite(bands[b])],dtype='float64'));actual=float(row[b]);error=abs(expected-actual)
 report['CSV_'+b]={'expected':expected,'actual':actual,'max_abs_error':error,'passed':error<1e-6}
(audit/'export-values.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));assert all(v['passed'] for v in report.values())
