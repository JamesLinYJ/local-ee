"""Normalize provider rasters into immutable, local COGs and versioned STAC items."""
import hashlib
import json
import os
import re
import math
import shutil
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds, Window
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping
from psycopg.types.json import Jsonb
from . import db

ROOT=Path(os.environ.get("DATA_ROOT","/data"))
S2_BANDS={"blue":"blue","green":"green","red":"red","nir":"nir","scl":"SCL"}
LS_BANDS={"blue":"blue","green":"green","red":"red","nir08":"nir","swir16":"swir16","qa_pixel":"QA_PIXEL"}

class IngestBudget:
    """Reserve conservative output bytes before writes to the shared data disk."""
    def __init__(self,root=None,max_bytes=2*1024**3,min_free=1024**3):
        self.root=Path(root) if root is not None else ROOT/"assets";self.max_bytes=max_bytes;self.min_free=min_free;self.used=0
    def reserve(self,amount,target=None):
        if amount<0 or self.used+amount>self.max_bytes:
            raise ValueError('Ingestion output byte budget exceeded')
        check=Path(target) if target is not None else self.root
        while not check.exists() and check != check.parent:check=check.parent
        if shutil.disk_usage(check).free < self.min_free+amount:
            raise ValueError('Insufficient free space for ingestion')
        self.used+=amount

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def collection_metadata(cid,title,bands,bbox,dates,units):
    return {"type":"Collection","stac_version":"1.0.0","id":cid,"title":title,
        "stac_extensions":["https://stac-extensions.github.io/datacube/v2.2.0/schema.json","https://stac-extensions.github.io/eo/v1.1.0/schema.json"],
        "description":"本地标准化副本；源数据及处理记录见 item 元数据。",
        "license":"proprietary","links":[],"extent":{"spatial":{"bbox":[bbox]},"temporal":{"interval":[dates]}},
        "cube:dimensions":{"x":{"type":"spatial","axis":"x","extent":[bbox[0],bbox[2]],"reference_system":4326},
            "y":{"type":"spatial","axis":"y","extent":[bbox[1],bbox[3]],"reference_system":4326},
            "t":{"type":"temporal","extent":dates},"bands":{"type":"bands","values":bands}},
        "summaries":{"eo:bands":[{"name":b,"common_name":b} for b in bands]},"gee:units":units}

def register(cid,meta,item,budget=None):
    encoded=json.dumps(item,sort_keys=True).encode();checksum=hashlib.sha256(encoded).hexdigest()
    budget=budget or IngestBudget()
    budget.reserve(len(encoded)+len(json.dumps(meta).encode())+65536,target=ROOT/"catalog")
    folder=ROOT/"catalog"/cid;folder.mkdir(parents=True,exist_ok=True)
    target=folder/(item["id"]+".json")
    tmp=target.with_suffix('.tmp');tmp.write_bytes(encoded);tmp.replace(target)
    with db.connect() as c:
        previous=c.execute("SELECT metadata FROM collections WHERE id=%s FOR UPDATE",(cid,)).fetchone()
        if previous and previous['metadata'].get('extent'):
            old=previous['metadata'];b=old['extent']['spatial']['bbox'][0];n=meta['extent']['spatial']['bbox'][0]
            b=[min(b[0],n[0]),min(b[1],n[1]),max(b[2],n[2]),max(b[3],n[3])]
            t=old['extent']['temporal']['interval'][0];u=meta['extent']['temporal']['interval'][0]
            dates=[min(t[0],u[0]),max(t[1],u[1])]
            meta['extent']={'spatial':{'bbox':[b]},'temporal':{'interval':[dates]}}
            meta['cube:dimensions']['x']['extent']=[b[0],b[2]];meta['cube:dimensions']['y']['extent']=[b[1],b[3]];meta['cube:dimensions']['t']['extent']=dates
        c.execute("INSERT INTO collections(id,metadata) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET metadata=EXCLUDED.metadata",(cid,Jsonb(meta)))
        c.execute("INSERT INTO items(id,collection_id,metadata,checksum) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",(item['id'],cid,Jsonb(item),checksum))
        # Keep immutable old files and job snapshots, but do not double-count revised acquisitions.
        if item['properties'].get('gee:source_id'):
            c.execute("UPDATE items SET active=false WHERE collection_id=%s AND id<>%s AND metadata->'properties'->>'gee:source_id'=%s AND COALESCE(metadata->'properties'->'gee:requested_bbox',metadata->'bbox')=%s",
                (cid,item['id'],item['properties']['gee:source_id'],Jsonb(item['properties'].get('gee:requested_bbox',item['bbox']))))
            c.execute("UPDATE items SET active=true WHERE id=%s",(item['id'],))
    (folder/'collection.json').write_text(json.dumps(meta,indent=2))

def write_cog(array,profile,path,budget=None):
    budget=budget or IngestBudget()
    budget.reserve(array.nbytes*2+1024*1024,target=path.parent)
    tmp=path.with_suffix('.part.tif')
    with rasterio.open(tmp,'w',driver='COG',height=array.shape[0],width=array.shape[1],count=1,
                       dtype='float32',nodata=-9999,crs=profile['crs'],transform=profile['transform'],compress='DEFLATE',blocksize=256) as dst:
        dst.write(np.where(np.isfinite(array),array,-9999).astype('float32'),1)
    with rasterio.open(tmp) as check:
        if check.width!=array.shape[1] or check.crs is None: raise ValueError('COG verification failed')
    tmp.replace(path)

def open_optical_asset(href):
    """Provider optical inputs have exactly one permitted dataset driver."""
    return rasterio.open(href,driver="GTiff")

def optical_item(item,cid,bbox,sign=lambda x:x,budget=None):
    if cid=='sentinel-2-l2a':
        if item.get('collection')!='sentinel-2-c1-l2a':
            raise ValueError('仅接收 Sentinel-2 Collection 1；旧 Earth Search L2A 存在偏移元数据歧义')
        bands=S2_BANDS
    elif cid=='landsat-c2-l2': bands=LS_BANDS
    elif cid=='cop-dem-glo-30': bands={'data':'elevation'}
    else: raise ValueError('Unknown source')
    # Include all source metadata in the version key: changed source products get new local assets.
    fingerprint=hashlib.sha256(json.dumps([item,bbox,'normalize-v2'],sort_keys=True).encode()).hexdigest()[:16]
    item_id=re.sub(r'[^a-zA-Z0-9_.-]','_',item['id'])+'-'+fingerprint
    if db.query('SELECT id FROM items WHERE id=%s',(item_id,),one=True): return item_id
    budget=budget or IngestBudget()
    source_json=json.dumps(item,indent=2)
    budget.reserve(len(source_json.encode()),target=ROOT/"assets")
    folder=ROOT/'assets'/cid/item_id;folder.mkdir(parents=True,exist_ok=True)
    (folder/'source.json').write_text(source_json)
    anchor=next(k for k in bands if k in item['assets'])
    with open_optical_asset(sign(item['assets'][anchor]['href'])) as src:
        b=transform_bounds('EPSG:4326',src.crs,*bbox)
        raw_window=from_bounds(*b,transform=src.transform)
        left,top=math.floor(raw_window.col_off),math.floor(raw_window.row_off)
        window=Window(left,top,math.ceil(raw_window.col_off+raw_window.width)-left,math.ceil(raw_window.row_off+raw_window.height)-top).intersection(Window(0,0,src.width,src.height))
        if window.width*window.height>4_000_000: raise ValueError('首版单景研究区限制为 400 万像素；缩小范围或分块同步')
        profile={'crs':src.crs,'transform':src.window_transform(window),'height':int(window.height),'width':int(window.width)}
    arrays={};processing={}
    for key,name in bands.items():
        asset=item['assets'].get(key)
        if not asset: continue
        with open_optical_asset(sign(asset['href'])) as src, WarpedVRT(src,**profile,resampling=Resampling.nearest) as vrt:
            raw=vrt.read(1,masked=True)
            rb=(asset.get('raster:bands') or [{}])[0]
            if name in {'SCL','QA_PIXEL'}: scale,offset=1,0
            elif cid=='sentinel-2-l2a':
                if 'scale' not in rb or 'offset' not in rb: raise ValueError('缺少 Sentinel-2 反射率 scale/offset，拒绝猜测')
                scale,offset=rb['scale'],rb['offset']
            elif cid=='landsat-c2-l2': scale,offset=rb.get('scale',0.0000275),rb.get('offset',-0.2)
            else: scale,offset=1,0
            arrays[name]=raw.astype('float32').filled(np.nan)*scale+offset
            processing[name]={'source_asset':key,'scale':scale,'offset':offset,'resampling':'nearest'}
    # Apply quality on the common grid, preserving quality bands for independent verification.
    if 'SCL' in arrays:
        valid=np.isin(arrays['SCL'],[4,5,6,7])
    elif 'QA_PIXEL' in arrays:
        qa=np.nan_to_num(arrays['QA_PIXEL'],nan=1).astype('uint16')
        valid=(qa & 0b111111)==0  # fill, dilated cloud, cirrus, cloud, shadow, snow
        # QA_RADSAT saturation is required for scientific surface reflectance use.
        sat=item['assets'].get('qa_radsat')
        if not sat: raise ValueError('Landsat 缺少 QA_RADSAT')
        with open_optical_asset(sign(sat['href'])) as src, WarpedVRT(src,**profile,resampling=Resampling.nearest) as vrt:
            valid &= vrt.read(1)==0
    else: valid=None
    assets={};units={}
    for name,arr in arrays.items():
        unit='1' if name!='elevation' else 'm';units[name]=unit
        if valid is not None and name not in {'SCL','QA_PIXEL'}: arr=np.where(valid,arr,np.nan)
        path=folder/(name+'.tif');write_cog(arr,profile,path,budget=budget)
        assets[name]={'href':'/data/'+str(path.relative_to(ROOT)),'type':'image/tiff; application=geotiff; profile=cloud-optimized','roles':['data'],
            'eo:bands':[{'name':name,'common_name':name}], 'raster:bands':[{'data_type':'float32','nodata':-9999,'scale':1,'offset':0,'unit':unit}],
            'proj:epsg':profile['crs'].to_epsg(),'proj:shape':[profile['height'],profile['width']],
            'proj:transform':list(profile['transform'])[:6], 'file:checksum':'sha256:'+sha256(path)}
    date=item['properties'].get('datetime') or item['properties'].get('start_datetime') or '2021-01-01T00:00:00Z'
    local={'type':'Feature','stac_version':'1.0.0','stac_extensions':['https://stac-extensions.github.io/eo/v1.1.0/schema.json','https://stac-extensions.github.io/projection/v1.1.0/schema.json'],
        'id':item_id,'collection':cid,'bbox':bbox,'geometry':mapping(box(*bbox)),'links':[],
        'properties':{'datetime':date,'proj:epsg':profile['crs'].to_epsg(),'gee:source_id':item['id'],'gee:source_collection':item.get('collection'),'gee:requested_bbox':bbox,
                      'gee:source_version':item['properties'].get('s2:processing_baseline',item['properties'].get('landsat:collection_number')),
                      'gee:processing':processing,'gee:cloud_mask':'SCL 4,5,6,7 / Landsat QA_PIXEL bits 0..5 and QA_RADSAT=0',
                      'gee:source_metadata':'/data/'+str((folder/'source.json').relative_to(ROOT))},'assets':assets}
    meta=collection_metadata(cid,{'sentinel-2-l2a':'Sentinel-2 L2A · 已去云反射率','landsat-c2-l2':'Landsat C2 L2 · 已去云反射率','cop-dem-glo-30':'Copernicus DEM · 30 m'}[cid],list(assets),bbox,[date,date],units)
    meta['license']=item.get('properties',{}).get('license','various')
    register(cid,meta,local,budget=budget)
    return item_id
