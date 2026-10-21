"""ERA5-Land hourly CDS accumulations -> UTC daily COGs, with original NetCDF retained."""
import hashlib
import json
import os
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.transform import from_origin
from shapely.geometry import box,mapping
from .ingest import ROOT,sha256,write_cog,register,collection_metadata,IngestBudget

def daily_values(ds):
    """Only ERA5-Land hourly single-level accumulation convention is accepted.

    Temperature: 00..23 UTC mean; precipitation for day D: D+1 00 UTC cumulative value.
    Missing hours produce NoData, never silently partial daily means or totals.
    """
    if 'valid_time' in ds.dims:ds=ds.rename({'valid_time':'time'})
    if 'time' not in ds.dims or not {'t2m','tp'}<=set(ds):raise ValueError('需要 time/valid_time、t2m、tp')
    ds=ds.sortby('time')
    times=pd.DatetimeIndex(ds.time.values)
    if times.has_duplicates or not all(times.minute==0):raise ValueError('时间轴重复或非整点')
    if ds.t2m.attrs.get('units') not in {'K','kelvin'} or ds.tp.attrs.get('units') not in {'m','m of water equivalent'}:
        raise ValueError('需要温度 K、累计降水 m，拒绝猜测单位')
    for name in ['t2m','tp']:
        if set(ds[name].dims)!={'time','latitude','longitude'}:raise ValueError('仅支持规则经纬网 hourly CDS 单层产品')
    temp=(ds.t2m-273.15).resample(time='1D').mean(skipna=False)
    count=ds.t2m.resample(time='1D').count()
    temp=temp.where(count==24)
    rain=ds.tp.sel(time=ds.time.dt.hour==0)*1000
    rain=rain.assign_coords(time=rain.time-np.timedelta64(1,'D'))
    # Significant negative precipitation is invalid. Tiny roundoff is clipped.
    rain=rain.where(rain>=-1e-5).clip(min=0)
    return xr.Dataset({'temperature':temp,'precipitation':rain}).sortby('latitude',ascending=False)

def ingest_netcdf(paths,start,end):
    budget=IngestBudget()
    paths=[Path(p) for p in paths]
    source_sha=[sha256(p) for p in paths]
    parts=[xr.open_dataset(p,engine="netcdf4") for p in paths]
    try:
        ds=xr.merge(parts,compat='no_conflicts')
        daily=daily_values(ds).sel(time=slice(start,end))
        lat=daily.latitude.values;lon=daily.longitude.values
        if len(lat)<2 or len(lon)<2:raise ValueError('研究区至少覆盖 2×2 气象网格')
        if lon[0]>lon[-1]:daily=daily.sortby('longitude');lon=daily.longitude.values
        dx=float(lon[1]-lon[0]);dy=float(lat[0]-lat[1])
        if not np.allclose(np.diff(lon),dx) or not np.allclose(np.diff(lat),-dy):raise ValueError('不规则经纬网')
        transform=from_origin(lon[0]-dx/2,lat[0]+dy/2,dx,dy)
        bbox=[float(lon[0]-dx/2),float(lat[-1]-dy/2),float(lon[-1]+dx/2),float(lat[0]+dy/2)]
        crs=rasterio.crs.CRS.from_epsg(4326);profile={'crs':crs,'transform':transform}
        count=0
        for timestamp in daily.time.values:
            day=str(np.datetime_as_string(timestamp,unit='D'));dt=day+'T00:00:00Z'
            suffix=hashlib.sha256(json.dumps(source_sha).encode()).hexdigest()[:12];iid='era5-land-'+day+'-'+suffix
            folder=ROOT/'assets'/'era5-land'/iid;folder.mkdir(parents=True,exist_ok=True);assets={}
            for band,unit in [('temperature','degree_Celsius'),('precipitation','mm')]:
                array=daily[band].sel(time=timestamp).transpose('latitude','longitude').values
                path=folder/(band+'.tif');write_cog(array,profile,path,budget=budget)
                assets[band]={'href':'/data/'+str(path.relative_to(ROOT)),'type':'image/tiff; application=geotiff; profile=cloud-optimized','roles':['data'],
                    'eo:bands':[{'name':band}], 'raster:bands':[{'nodata':-9999,'unit':unit,'scale':1,'offset':0,'data_type':'float32'}],
                    'proj:epsg':4326,'proj:shape':list(array.shape),'proj:transform':list(transform)[:6],'file:checksum':'sha256:'+sha256(path)}
            item={'type':'Feature','stac_version':'1.0.0','stac_extensions':['https://stac-extensions.github.io/projection/v1.1.0/schema.json'],
                'id':iid,'collection':'era5-land','geometry':mapping(box(*bbox)),'bbox':bbox,'links':[],
                'properties':{'datetime':dt,'proj:epsg':4326,'gee:source_sha256':source_sha,'gee:time_definition':'UTC day [00:00, next 00:00); temperature mean 24 samples; rainfall next-day 00 UTC accumulation',
                'gee:processing':'ERA5-Land hourly CDS accumulation convention; normalize-v1'},'assets':assets}
            meta=collection_metadata('era5-land','ERA5-Land · UTC 日温度 / 降水',list(assets),bbox,[dt,dt],{'temperature':'degree_Celsius','precipitation':'mm'})
            meta['license']='CC-BY-4.0';register('era5-land',meta,item,budget=budget);count+=1
        return count
    finally:
        for p in parts:p.close()

def retrieve(config,settings):
    import cdsapi
    key=os.environ.get('CDSAPI_KEY')
    if not key:raise ValueError('ERA5-Land 需要同步服务专用 CDSAPI_KEY，并先在 CDS 接受数据条款')
    start=date.fromisoformat(str(config['start']));end=date.fromisoformat(str(config['end']))
    if (end-start).days>31:raise ValueError('首版按月同步 ERA5-Land；时间范围最多 31 天')
    dates=[start+timedelta(days=i) for i in range((end-start).days+2)]
    bbox=config['bbox'];area=[max(bbox[3],bbox[1]+.2),bbox[0],bbox[1],max(bbox[2],bbox[0]+.2)]
    folder=ROOT/'raw'/'era5-land';folder.mkdir(parents=True,exist_ok=True)
    client=cdsapi.Client(url='https://cds.climate.copernicus.eu/api',key=key,quiet=True,debug=False)
    paths=[]
    # Requests are split by month and variable, avoiding accidental Cartesian dates and ZIP step-type mixes.
    for year,month in sorted({(d.year,d.month) for d in dates}):
        for variable in ['2m_temperature','total_precipitation']:
            req={'variable':[variable],'year':str(year),'month':f'{month:02}','day':[f'{d.day:02}' for d in dates if (d.year,d.month)==(year,month)],
                 'time':[f'{h:02}:00' for h in range(24)],'data_format':'netcdf','download_format':'unarchived','area':area}
            keyhash=hashlib.sha256(json.dumps(req,sort_keys=True).encode()).hexdigest()[:20];target=folder/(keyhash+'.nc')
            if not target.exists():
                result=client.retrieve('reanalysis-era5-land',req)
                # CDS's response identifies the download host; our checked downloader and egress proxy enforce the allowlist.
                from .sync import download
                url=result.location if hasattr(result,'location') else result.reply['location']
                download(url,target)
                (folder/(keyhash+'.request.json')).write_text(json.dumps(req,indent=2))
            paths.append(target)
    # Concatenate same variable across month boundaries before merging variables.
    # xarray merge accepts disjoint times and aligns the time coordinate.
    return ingest_netcdf(paths,str(start),str(end))
