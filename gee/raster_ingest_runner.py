"""Credential-free GeoTIFF validation/normalization, invoked only in an isolated container."""
import hashlib,json,math,os,re,sys
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import transform_bounds


def run(source=Path('/input/content'),job=Path('/job')):
    config=json.loads((job/'ingest.json').read_text())
    if source.stat().st_size!=config['expected_size']:raise ValueError('Source file size changed')
    h=hashlib.sha256()
    with source.open('rb') as stream:
        while chunk:=stream.read(1024*1024):h.update(chunk)
    if h.hexdigest()!=config['expected_sha256']:raise ValueError('Source file checksum changed')
    out=job/'out';out.mkdir(exist_ok=True)
    with rasterio.Env(GDAL_PAM_ENABLED='NO',GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',PROJ_NETWORK='OFF'), rasterio.open(source,driver='GTiff') as src:
        if not src.crs or not 1<=src.count<=32 or src.width*src.height>4_000_000 or src.width*src.height*src.count>64_000_000:raise ValueError('需要有效 CRS，最多 32 波段、单波段 400 万像素、总计 6400 万像素')
        if not all(math.isfinite(x) for x in src.transform):raise ValueError('Invalid raster transform')
        bbox=list(transform_bounds(src.crs,'EPSG:4326',*src.bounds,densify_pts=21))
        if not all(math.isfinite(x) for x in bbox) or not (-180<=bbox[0]<bbox[2]<=180 and -90<=bbox[1]<bbox[3]<=90):raise ValueError('影像地理范围无效或跨越日期变更线')
        names=config['options']['bands'] or [name or f'band_{index+1}' for index,name in enumerate(src.descriptions)]
        if len(names)!=src.count or len(set(names))!=len(names) or any(not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,63}',name) for name in names):raise ValueError('请提供与原文件波段数一致的唯一波段名（字母开头）')
        report={'bbox':bbox,'crs':str(src.crs),'shape':[src.height,src.width],'bands':[],'source_sha256':h.hexdigest(),'normalization':'float32; original scale/offset applied; original mask preserved; no automatic cloud masking'}
        for index,name in enumerate(names):
            scale=float(src.scales[index]);offset=float(src.offsets[index])
            if not math.isfinite(scale) or not math.isfinite(offset):raise ValueError('Invalid source scale/offset')
            raw=src.read(index+1,masked=True).astype('float64').filled(np.nan)
            values=raw*scale+offset
            with np.errstate(over='ignore',invalid='ignore'):normalized=values.astype('float32')
            if np.any(np.isfinite(values)&~np.isfinite(normalized)):raise ValueError('数值超出 float32 范围')
            valid=np.isfinite(values);error=float(np.abs(values[valid]-normalized[valid]).max(initial=0))
            filename=f'band-{index+1:02d}.tif'
            with rasterio.open(out/filename,'w',driver='COG',width=src.width,height=src.height,count=1,dtype='float32',nodata=float('nan'),crs=src.crs,transform=src.transform,compress='DEFLATE',blocksize=256) as dst:
                dst.write(np.where(valid,normalized,np.nan),1);dst.set_band_description(1,name)
            report['bands'].append({'name':name,'filename':filename,'scale':scale,'offset':offset,'source_dtype':src.dtypes[index],'valid_pixels':int(valid.sum()),'float32_max_absolute_error':error})
    (out/'ingest-report.json').write_text(json.dumps(report,allow_nan=False))
    print('GeoTIFF 校验与 COG 标准化完成；'+str(len(names))+' 个波段。')


if __name__=='__main__':run(Path(sys.argv[1]),Path(sys.argv[2]))
