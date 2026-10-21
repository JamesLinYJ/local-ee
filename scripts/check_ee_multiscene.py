"""Official SDK -> compiler -> real isolated GeoTrellis, with NumPy references.

Synthetic, labelled fixtures stay outside the live STAC/database. This is local
algorithm acceptance, not a comparison with Google's proprietary service.
Requires a NEW GEE_AUDIT_DIR and the native macOS engine.
"""
import copy
import datetime as dt
import hashlib
import json
import os
import shutil
from pathlib import Path
import warnings

import sys
import time
import uuid
import importlib.util
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.features import geometry_mask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gee import graph
from gee.ee_translate import compile_expression

AUDIT = Path(os.environ['GEE_AUDIT_DIR']).resolve()
AUDIT.mkdir(parents=True, exist_ok=False)
JOB = AUDIT/'engine'; JOB.mkdir(); (JOB/'out').mkdir(mode=0o777); (JOB/'out').chmod(0o777)
NAMES = ['blue','green','red','nir','SCL']
TRANSFORM = from_origin(763000,2470000,10,10)
BBOX = list(transform_bounds(32649,4326,763000,2469840,763160,2470000))
GEOMETRY = {'type':'Polygon','coordinates':[[[BBOX[0],BBOX[1]],[BBOX[2],BBOX[1]],[BBOX[2],BBOX[3]],[BBOX[0],BBOX[3]],[BBOX[0],BBOX[1]]]]}
PATTERNS = {
    'a': {'nir':[-1,0,1,3,5,np.nan,np.nan,4], 'red':[3,0,1,1,3,2,np.nan,4],
          'green':[1,np.nan,0,1,1,1,1,1], 'blue':[9,9,9,np.nan,9,9,9,.2], 'SCL':[4,4,8,4,6,4,4,4]},
    'b': {'nir':[9,0,7,np.nan,1,np.nan,8,6], 'red':[1,0,2,2,2,np.nan,3,6],
          'green':[1]*8, 'blue':[.1]*8, 'SCL':[4,4,4,8,4,4,4,4]},
    'c': {'nir':[5,2,2,2,9,1,1,1], 'red':[3]*8, 'green':[1]*8, 'blue':[.2]*8, 'SCL':[4]*8},
}
arrays = {i:{b:np.tile(np.array(p,dtype='float32'),(16,2)) for b,p in bands.items()} for i,bands in PATTERNS.items()}
metadata = {'id':'sentinel-2-l2a','type':'Collection','stac_version':'1.0.0','description':'Synthetic EE compatibility fixture only',
    'license':'proprietary','links':[], 'extent':{'spatial':{'bbox':[BBOX]},'temporal':{'interval':[['1970-01-01T00:00:01Z','1970-01-01T00:00:02Z']]}},
    'stac_extensions':['https://stac-extensions.github.io/datacube/v2.2.0/schema.json','https://stac-extensions.github.io/eo/v1.1.0/schema.json'],
    'summaries':{'eo:bands':[{'name':b,'common_name':b} for b in NAMES]},
    'cube:dimensions':{'t':{'type':'temporal','extent':['1970-01-01T00:00:01Z','1970-01-01T00:00:02Z']},
        'x':{'type':'spatial','axis':'x','extent':[BBOX[0],BBOX[2]],'reference_system':4326},
        'y':{'type':'spatial','axis':'y','extent':[BBOX[1],BBOX[3]],'reference_system':4326},'bands':{'type':'bands','values':NAMES}}}
items = []
for iid,ms in [('a',1000),('b',1001),('c',2000)]:
    assets = {}; (JOB/iid).mkdir()
    for band in NAMES:
        path=JOB/iid/(band+'.tif')
        with rasterio.open(path,'w',driver='GTiff',width=16,height=16,count=1,dtype='float32',crs=32649,transform=TRANSFORM,nodata=-9999,tiled=True,blockxsize=256,blockysize=256) as f:
            f.write(np.where(np.isfinite(arrays[iid][band]),arrays[iid][band],-9999).astype('float32'),1)
        assets[band]={'href':str(path),'type':'image/tiff; application=geotiff','roles':['data'],
            'eo:bands':[{'name':band,'common_name':band}],'proj:epsg':32649,'proj:shape':[16,16],'proj:transform':list(TRANSFORM)[:6],
            'raster:bands':[{'data_type':'float32','scale':1,'offset':0,'nodata':-9999}]}
    items.append({'id':iid,'type':'Feature','stac_version':'1.0.0','bbox':BBOX,'geometry':GEOMETRY,'collection':'sentinel-2-l2a','links':[],
        'properties':{'datetime':dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat().replace('+00:00','Z'),
            'system:time_start':ms,'system:index':iid,'proj:epsg':32649,'CLOUDY_PIXEL_PERCENTAGE':{'a':20,'b':5,'c':90}[iid]},'assets':assets,
        'stac_extensions':['https://stac-extensions.github.io/eo/v1.1.0/schema.json','https://stac-extensions.github.io/projection/v1.1.0/schema.json']})
sdk = json.loads((ROOT/'tests/fixtures/ee-sdk-1.7.49.json').read_text())
mask_sdk = json.loads((ROOT/'tests/fixtures/ee-mask-1.7.49.json').read_text())
expressions = {**sdk['expressions'], **mask_sdk['raster_expressions']}
CASES = ['median','mosaic','reverseMosaic','sum','count','cloudMask','nd','expression','whereMasked','whereConstant','constantMath','clamp','unitScale','reduceBands','reduceCollection','toBands',
         'fromImagesMean','fromImagesDuplicateSum','fromImagesDuplicateCount','fromImagesSortedMosaic','fromImagesPeriods','mergedMean']
if os.environ.get('GEE_EE_CASES'):
    CASES = os.environ['GEE_EE_CASES'].split(',')
    if not CASES or any(name not in expressions for name in CASES):
        raise ValueError('GEE_EE_CASES must select existing official SDK fixture names')
if 'unmaskMappedMean' in CASES:
    # Item footprints differ even when two observations share exactly the same
    # timestamp. Do not let a collection-wide union revive each frame's exterior.
    middle=(BBOX[0]+BBOX[2])/2
    for item,west,east in [(items[1],middle,BBOX[2]),(items[2],BBOX[0],middle)]:
        south,north=BBOX[1],BBOX[3]
        item['geometry']={'type':'Polygon','coordinates':[[[west,south],[east,south],
                         [east,north],[west,north],[west,south]]]}
    items[1]['properties']['datetime']=items[0]['properties']['datetime']
    items[1]['properties']['system:time_start']=items[0]['properties']['system:time_start']
merged={}; dedup={}; outputs=[]; expected_names=[]

def append(process,args):
    key=json.dumps([process,args],sort_keys=True)
    if key not in dedup:
        name='n'+str(len(merged)); merged[name]={'process_id':process,'arguments':args}; dedup[key]={'from_node':name}
    return dedup[key]

for name in CASES:
    compiled=compile_expression(expressions[name],[metadata],{'sentinel-2-l2a':items})
    remap={}
    def refs(v):
        if isinstance(v,list):return [refs(x) for x in v]
        if isinstance(v,dict):
            if 'process_graph' in v:return copy.deepcopy(v)  # callback has its own scope
            if 'from_node' in v:return remap[v['from_node']]
            return {k:refs(x) for k,x in v.items()}
        return v
    for old,node in compiled['process_graph'].items():
        remap[old]=append(node['process_id'],refs(node['arguments']))
        if node.get('result'): result=remap[old]
    labels=[name+'__'+b for b in compiled['bands']]; expected_names.extend(labels)
    outputs.append(append('rename_labels',{'data':result,'dimension':'bands','target':labels}))
result=outputs[0]
for other in outputs[1:]: result=append('merge_cubes',{'cube1':result,'cube2':other})
result=append('save_result',{'data':result,'format':'GTiff'}); merged[result['from_node']]['result']=True
graph.validate(merged)
for key,(cid,selection) in graph.collection_loads(merged).items():
    catalog=copy.deepcopy(metadata); catalog['links']=[]
    for iid in selection:
        filename=f'item-{key}-{iid}.json'; item=next(x for x in items if x['id']==iid)
        (JOB/filename).write_text(json.dumps(item)); catalog['links'].append({'rel':'item','href':str(JOB/filename),'type':'application/geo+json'})
    (JOB/('catalog-'+key+'.json')).write_text(json.dumps(catalog))
(JOB/'graph.json').write_text(json.dumps(graph.materialize(merged,{'sentinel-2-l2a':metadata},str(JOB))))
spec=importlib.util.spec_from_file_location('native_launch',ROOT/'scripts/native.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
os.environ.update(launcher.environment())
from gee.native.runtime import NativeClient
engine=json.loads((ROOT/'.native/engine-lock.json').read_text())
client=NativeClient(); task=client.launch({'id':str(uuid.uuid4()),'kind':'batch'},folder=JOB)
print('Running native engine',engine['architecture'],'nodes',len(merged),flush=True)
try:
    deadline=time.monotonic()+300
    while time.monotonic()<deadline:
        task.reload()
        if task.status=='exited':break
        time.sleep(1)
    else:raise RuntimeError('Native engine timeout')
    (AUDIT/'engine.log').write_bytes(task.logs())
    if task.attrs['State']['ExitCode']!=0:raise RuntimeError('Engine failed; see '+str(AUDIT/'engine.log'))
finally:
    task.reload()
    if task.status in {'running','starting'}:task.stop()
    task.remove()
paths=list((JOB/'out').glob('*.tif')); assert len(paths)==1,paths
report=[]
with rasterio.open(paths[0]) as output:
    warped={}
    for iid in arrays:
        warped[iid]={}
        for band in NAMES:
            target=np.full(output.shape,np.nan,dtype='float32')
            reproject(arrays[iid][band],target,src_transform=TRANSFORM,src_crs=32649,src_nodata=np.nan,
                dst_transform=output.transform,dst_crs=output.crs,dst_nodata=np.nan,resampling=Resampling.nearest)
            warped[iid][band]=target
    a,b,c=[warped[x] for x in 'abc']; x,y=a['nir'],a['red']; stack=np.stack([x,b['nir']]); count=np.isfinite(stack).sum(0)
    with warnings.catch_warnings(),np.errstate(divide='ignore',invalid='ignore'):
        warnings.simplefilter('ignore',RuntimeWarning)
        cloud=np.stack([np.where(warped[i]['SCL']==4,warped[i]['nir'],np.nan) for i in 'ab'])
        expected={
            'median':[np.nanmedian(stack,axis=0)], 'mosaic':[np.where(np.isfinite(b['nir']),b['nir'],x)],
            'reverseMosaic':[np.where(np.isfinite(x),x,b['nir'])], 'sum':[np.where(count>0,np.nansum(stack,axis=0),np.nan)],
            'count':[np.where(count>0,count,np.nan)], 'cloudMask':[np.nanmedian(cloud,axis=0)],
            'nd':[np.where((x>=0)&(y>=0)&(x+y!=0),(x-y)/(x+y),np.nan)],
            'expression':[np.where(x+y==0,0,(x-y)/(x+y))],
            'whereMasked':[np.where(np.isfinite(x)&np.isfinite(a['green'])&(a['green']!=0)&np.isfinite(a['blue']),a['blue'],x)],
            'whereConstant':[np.where(np.isfinite(x)&np.isfinite(y)&(y>2),0,x)], 'constantMath':[x*2],
            'clamp':[np.clip(x,2,6)], 'unitScale':[(x-1)/4], 'reduceBands':[np.nanmean(np.stack([x,y]),axis=0)],
            'reduceCollection':[np.nanmean(np.stack([x,b['nir'],c['nir']]),axis=0)], 'toBands':[x,b['nir']],
            'fromImagesMean':[np.nanmean(stack,axis=0)],'fromImagesPeriods':[np.nanmean(stack,axis=0)],'mergedMean':[np.nanmean(stack,axis=0)],
            'fromImagesDuplicateSum':[x*2],'fromImagesDuplicateCount':[np.where(np.isfinite(x),2,np.nan)],
            'fromImagesSortedMosaic':[np.where(np.isfinite(b['nir']),b['nir'],np.where(np.isfinite(x),x,c['nir']))],
            'toDouble':[x.astype('float64')], 'doubleToFloat':[x],
            'perImageDateMean':[np.nanmean(np.stack([warped[i]['nir'] * seconds for i,seconds in [('a',1.0),('b',1.001),('c',2.0)]]),axis=0)],
            'unmaskZero':[np.where(np.isfinite(x),x,0).astype('float64')],
            'unmaskLarge':[np.where(np.isfinite(x),x.astype('float64'),16_777_219)],
            'unmaskRaster':[np.where(np.isfinite(x),x,y).astype('float64')],
            'unmaskDouble':[np.where(np.isfinite(x),x.astype('float64'),1_700_000_000_001)],
        }
        # Independently rasterize the SDK fixture's planar clip, after source
        # reprojection onto the result grid. Filling cannot revive clip-exterior cells.
        clip_bounds=[113.55299439326834,22.314269909925745,113.5537966618118,22.315726168412937]
        cw,cs,ce,cn=clip_bounds
        clip={'type':'Polygon','coordinates':[[[cw,cs],[ce,cs],[ce,cn],[cw,cn],[cw,cs]]]}
        from rasterio.warp import transform_geom
        input_footprint=geometry_mask([transform_geom(4326,output.crs,GEOMETRY)],
            out_shape=output.shape,transform=output.transform,invert=True)
        for name in ('unmaskZero','unmaskLarge','unmaskRaster','unmaskDouble'):
            expected[name]=[np.where(input_footprint,expected[name][0],np.nan)]
        inside=geometry_mask([transform_geom(4326,output.crs,clip)],out_shape=output.shape,
                             transform=output.transform,invert=True)
        expected['unmaskClipped']=[np.where(inside,expected['unmaskLarge'][0],np.nan)]
        if 'unmaskMappedMean' in CASES:
            filled=[]
            for item in items:
                footprint=geometry_mask([transform_geom(4326,output.crs,item['geometry'])],
                    out_shape=output.shape,transform=output.transform,invert=True)
                values=warped[item['id']]['nir']
                filled.append(np.where(footprint,np.where(np.isfinite(values),values,0),np.nan))
            expected['unmaskMappedMean']=[np.nanmean(np.stack(filled),axis=0)]
        # Independent argmax/gather keeps all output bands tied to the same
        # source scene. A missing payload in the winning scene stays missing.
        for name,order in [('qualityMosaic','ab'),('qualityMosaicReverse','ba'),('qualityMosaicExplicit','abc')]:
            quality=np.stack([warped[i]['nir'] for i in order]);valid_quality=np.isfinite(quality)
            winner=len(order)-1-np.argmax(np.where(valid_quality,quality,-np.inf)[::-1],axis=0)
            expected[name]=[]
            for band in ['nir','blue']:
                payload=np.stack([warped[i][band] for i in order])
                gathered=np.take_along_axis(payload,winner[None,...],axis=0)[0]
                expected[name].append(np.where(valid_quality.any(axis=0),gathered,np.nan))
    for index,name in enumerate(CASES):
        for band_index,reference in enumerate(expected[name]):
            suffix = ['a_nir','b_nir'][band_index] if name=='toBands' else {'reduceBands':'mean','reduceCollection':'nir_mean','nd':'nd','expression':'out'}.get(name,'nir')
            if name.startswith('qualityMosaic'):suffix=['nir','blue'][band_index]
            label=name+'__'+suffix
            position=expected_names.index(label)+1
            actual=output.read(position,masked=True).filled(np.nan); valid=np.isfinite(reference)&np.isfinite(actual)
            mismatch=int(np.sum(np.isfinite(reference)!=np.isfinite(actual))); error=float(np.abs(actual[valid]-reference[valid]).max(initial=0))
            passed=mismatch==0 and bool(np.allclose(actual[valid],reference[valid],rtol=1e-6,atol=1e-6))
            report.append({'case':label,'valid_pixels':int(valid.sum()),'mask_mismatches':mismatch,'max_abs_error':error,'passed':passed})
            print(report[-1],flush=True)
    expected_dtype={'toDouble':'float64','doubleToFloat':'float32',
                    **{name:'float64' for name in mask_sdk['raster_expressions']},
                    'unmaskMappedMean':'float32'}.get(CASES[0]) if len(CASES)==1 else None
    dtype_passed=expected_dtype is None or all(value==expected_dtype for value in output.dtypes)
    result={'native_engine':engine,'sdk':sdk['sdk'],'upstream_commit':sdk['source_commit'],'graph_nodes':len(merged),
        'output_dtypes':list(output.dtypes),
        'expected_output_dtype':expected_dtype,'dtype_passed':dtype_passed,
        'shape':list(output.shape),'crs':str(output.crs),'output_bands':list(output.descriptions),'expected_band_order':expected_names,
        'fixture':'Synthetic three-scene, per-band NoData, millisecond timestamps. Never added to live catalog.',
        'distinct_scene_footprints_and_identical_timestamps':'unmaskMappedMean' in CASES,
        'reference':'Independent NumPy, reprojected with Rasterio to the exact result grid. No Google-service comparison.',
        'cases':report,'passed':dtype_passed and all(x['passed'] for x in report)}
(AUDIT/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
assert result['passed'],report
# These inputs were generated in this new, isolated audit directory. Keep the
# scientific output and a checksum manifest, and regenerate fixtures with this
# script when needed instead of accumulating tiled TIFF copies after success.
input_records=[]
for iid in arrays:
    folder=JOB/iid
    for path in sorted(folder.iterdir()):
        input_records.append({'file':str(path.relative_to(AUDIT)),'bytes':path.stat().st_size,
                              'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    shutil.rmtree(folder)
(AUDIT/'generated-input-cleanup.json').write_text(json.dumps({'inputs':input_records,
    'reproduction':'scripts/check_ee_multiscene.py regenerates synthetic inputs; graph, output and logs retained'},indent=2)+'\n')
