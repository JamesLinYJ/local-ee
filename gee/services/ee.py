"""Local EE use cases; pure compilation is separate from identity, jobs and files."""
import csv
import io
import json
import math
import os
import re
import time
from pathlib import Path
from datetime import datetime
from openeo_driver.users import User
from .. import db, graph
from ..artifacts import artifact_path
from ..ee_translate import compile_expression, UnsupportedEEError
from .ee_exports import export_options
from .ee_budget import pixel_budget, sample_input_budget
from . import ee_sample_results
from . import ee_runtime_results
from .ee_idempotency import idempotency_record, validate_request_id
from .ee_events import check_event_capacity, record_event
from ..table_graph import table_input_graph
from ..table_values import columns as table_columns

DATA=Path(os.environ.get('DATA_ROOT','/data'))
EE_TASK_STATES={'created':'UNSUBMITTED','queued':'READY','running':'RUNNING','finished':'COMPLETED','error':'FAILED','canceled':'CANCELLED'}
OPERATION_STATES={'created':'PENDING','queued':'PENDING','running':'RUNNING','finished':'SUCCEEDED','error':'FAILED','canceled':'CANCELLED'}


def catalog_snapshot():
    with db.connect() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        catalog=[r['metadata'] for r in c.execute('SELECT metadata || managed_metadata AS metadata FROM collections WHERE enabled ORDER BY id')]
        rows=c.execute('SELECT i.collection_id,i.metadata FROM items i JOIN collections c ON c.id=i.collection_id WHERE i.active AND c.enabled ORDER BY i.id').fetchall()
    items={m['id']:[] for m in catalog}
    for row in rows:
        item=row['metadata'];props=item['properties'];source={}
        href=props.get('gee:source_metadata')
        if href:
            p=DATA/href.removeprefix('/data/')
            # This is metadata owned by the ingestion service, never an arbitrary EE path.
            if p.is_symlink() or not p.resolve().is_relative_to((DATA/'assets').resolve()):
                raise ValueError('Unsafe source metadata path')
            if p.is_file() and p.stat().st_size<=1048576:
                source=json.loads(p.read_text()).get('properties',{})
        date=props.get('datetime')
        if date:props['system:time_start']=datetime.fromisoformat(date.replace('Z','+00:00')).timestamp()*1000
        props['system:index']=props.get('gee:source_id',item['id'])
        cloud=source.get('eo:cloud_cover',props.get('eo:cloud_cover'))
        if cloud is not None:
            props['eo:cloud_cover']=cloud;props['CLOUDY_PIXEL_PERCENTAGE']=cloud
        items.setdefault(row['collection_id'],[]).append(item)
    return catalog,items


def geometry(value,catalog,items):
    if isinstance(value,dict) and value.get('type') in {'Point','Polygon','MultiPolygon','Feature'}:
        result=value.get('geometry',value)
    else:
        decoded=compile_expression(value,catalog,items)
        if decoded['kind']!='value':raise UnsupportedEEError('An explicit geometry is required')
        result=decoded['value']
    from shapely.geometry import shape,mapping
    geo=shape(result)
    if geo.is_empty or not geo.is_valid or any(not math.isfinite(x) for x in geo.bounds):raise ValueError('Invalid geometry')
    w,s,e,n=geo.bounds
    if w < -180 or e > 180 or s < -90 or n >90:raise ValueError('Only WGS84 lon/lat geometry is supported')
    return mapping(geo)


def _script_parent(account):
    """Resolve only the running parent attached to a database-backed script token."""
    if account.get('scope')!='script':return None
    jid=account.get('job_id')
    if not jid:raise ValueError('Script token is not bound to a running parent job')
    row=db.query("SELECT id,language,status FROM jobs WHERE id::text=%s AND user_id=%s AND kind='script'",(str(jid),account['user_id']),one=True)
    if not row or row['status']!='running' or row['language'] not in {'javascript','python'}:
        raise ValueError('Script parent job is no longer running')
    return row


def _check_task_scope(row,account,parent):
    if account.get('scope')=='script' and str(row['context'].get('source_job_id'))!=str(parent['id']):
        # Do not expose the existence or state of a sibling task to a script token.
        from openeo_driver.errors import JobNotFoundException
        raise JobNotFoundException(str(row['id']))


def _task_type(row):
    context=row.get('context') or {}
    if context.get('result_kind') in {'region','runtime_json'}:return 'EXPORT_FEATURES'
    for node in (row.get('process') or {}).get('process_graph',{}).values():
        if node.get('process_id')=='save_result':
            return 'EXPORT_FEATURES' if node.get('arguments',{}).get('format')=='CSV' else 'EXPORT_IMAGE'
    return 'EXPORT_IMAGE'


def _task_status(row):
    return {'id':str(row['id']),'state':EE_TASK_STATES[row['status']],
            'description':row.get('title',''),'task_type':_task_type(row),
            'error_message':row.get('error')}


def _operation(row):
    status=OPERATION_STATES[row['status']]
    operation={'name':'operations/'+str(row['id']),
               'metadata':{'state':status,'description':row.get('title',''),'type':_task_type(row)},
               'done':status in {'SUCCEEDED','FAILED','CANCELLED'}}
    if status=='FAILED' and row.get('error'):
        operation['error']={'code':13,'message':str(row['error'])[:500]}
    return operation


def numeric(value,maximum=1e9):
    values=value if isinstance(value,list) else [value]
    if not values or len(values)>3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>maximum for v in values):raise ValueError('Expected finite numeric visualization values')
    return value


def visualization(value):
    if not isinstance(value,dict):raise ValueError('visParams must be an object')
    unknown=set(value)-{'bands','min','max','gamma','palette','opacity','forceRgbOutput'}
    if unknown:raise UnsupportedEEError('Unsupported visualization options: '+', '.join(sorted(unknown)))
    out={}
    for key in ['min','max','gamma']:
        if key in value:out[key]=numeric(value[key])
    if 'gamma' in out and any(v<=0 for v in (out['gamma'] if isinstance(out['gamma'],list) else [out['gamma']])):raise ValueError('gamma must be positive')
    if 'bands' in value:
        bands=value['bands'].split(',') if isinstance(value['bands'],str) else value['bands']
        if not isinstance(bands,list) or not 1<=len(bands)<=3 or any(not isinstance(b,str) or len(b)>128 for b in bands):raise ValueError('Map bands must contain 1..3 band names')
        out['bands']=bands
    if 'palette' in value:
        from PIL import ImageColor
        colors=value['palette'].split(',') if isinstance(value['palette'],str) else value['palette']
        if not isinstance(colors,list) or not 1<=len(colors)<=256:raise ValueError('palette requires 1..256 colors')
        for color in colors:
            if not isinstance(color,str) or len(color)>64:raise ValueError('Invalid color')
            ImageColor.getrgb('#'+color if re.fullmatch('[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}',color) else color)
        out['palette']=colors
    return out


def make_job(backend,account,compiled,title,fmt,context,start,request_id=None,request_payload=None):
    process=compiled['process_graph']
    result_ids=[key for key,node in process.items() if node.get('result') is True]
    if len(result_ids)!=1:raise ValueError('Compiler output requires one result')
    result_id=result_ids[0]
    for node in process.values():node.pop('result',None)
    key='gee_result'
    process[key]={'process_id':'save_result','arguments':{'data':{'from_node':result_id},'format':fmt},'result':True}
    graph.validate(process)
    parent=_script_parent(account)
    parent_id=str(parent['id']) if parent else None
    language=parent['language'] if parent else 'javascript'
    context={**context,'protocol':'earthengine','source_job_id':parent_id,'bands':compiled.get('bands',[]),'warnings':compiled.get('warnings',[]),'pixel_budget':compiled.get('pixel_budget')}
    if compiled.get('sample_budget') is not None:
        context['sample_budget']=compiled['sample_budget']
    if request_id is not None and request_payload is None:
        raise ValueError('EE export request payload is required for idempotency')
    idempotency=idempotency_record(request_id,request_payload)
    internal={'scope':account['scope'],'job_id':parent_id,
              'ee_task_context':context,'ee_task_language':language}
    if idempotency:
        if parent_id is None:raise ValueError('EE export request IDs require a script-scoped parent')
        internal['ee_idempotency']=idempotency
        context.update(idempotency)
    result=backend.batch_jobs.create_job(user=User(account['user_id'],internal_auth_data=internal),process={'process_graph':process},api_version='1.2',metadata={'title':str(title)[:200]})
    if start:backend.batch_jobs.start_job(result.id,User(account['user_id']))
    return {'job_id':result.id,'warnings':compiled.get('warnings',[])}


def dispatch(backend,account,payload):
    if not isinstance(payload,dict):raise ValueError('Expected an object')
    action=payload.get('action');options=payload.get('options') or {}
    if not isinstance(options,dict):raise ValueError('options must be an object')
    request_id=payload.get('request_id')
    if request_id is not None:
        if action not in {'export_image','export_table'}:raise ValueError('request_id is valid only for EE export actions')
        request_id=validate_request_id(request_id)
    parent=_script_parent(account)
    if action=='list':
        if parent is None:raise UnsupportedEEError('Task.list requires a script-scoped local session')
        rows=db.query("""SELECT id,title,status,error,context,process FROM jobs
            WHERE user_id=%s AND kind='batch' AND context->>'protocol'='earthengine'
            AND context->>'source_job_id'=%s AND context->>'result_kind'='export'
            ORDER BY created DESC LIMIT 100""",(account['user_id'],str(parent['id'])))
        return {'operations':[_operation(row) for row in rows]}
    if action=='map_zoom':
        zoom=options.get('zoom')
        if set(options)!={'zoom'} or isinstance(zoom,bool) or not isinstance(zoom,(int,float)) or not math.isfinite(zoom) or not 0<=zoom<=22:
            raise ValueError('zoom must be a finite number between 0 and 22')
        record_event(account,{'type':'map_view','zoom':zoom});return {'value':True}
    if action in {'start','status','result','cancel'}:
        row=db.job(str(payload.get('job_id','')),account['user_id'])
        if row['context'].get('protocol')!='earthengine':raise ValueError('Not an Earth Engine adapter task')
        _check_task_scope(row,account,parent)
        if action=='start':
            backend.batch_jobs.start_job(str(row['id']),User(account['user_id']))
            return {'value':_task_status(db.job(str(row['id']),account['user_id']))}
        if action=='cancel':
            backend.batch_jobs.cancel_job(str(row['id']),account['user_id'])
            return {'value':_task_status(db.job(str(row['id']),account['user_id']))}
        if action=='status':return {'value':_task_status(row)}
        if row['status'] in {'error','canceled'}:raise ValueError(row.get('error') or row['status'])
        if row['status']!='finished':return {'pending':True,'job_id':str(row['id'])}
        if row['context'].get('result_kind')=='samples':
            return {'value':ee_sample_results.read_result(DATA,row)}
        if row['context'].get('result_kind')=='runtime_json':
            return {'value':ee_runtime_results.read_result(DATA,row)}
        if row['context'].get('result_kind')!='region':raise ValueError('Task is not a regional value result')
        names=[n for n in row['assets'] if n.endswith('.csv')]
        if len(names)!=1:raise ValueError('Expected one regional CSV result')
        p=artifact_path(DATA,row['id'],names[0])
        if p.stat().st_size>1048576:raise ValueError('Regional value exceeds response budget')
        rows=list(csv.DictReader(io.StringIO(p.read_text())))
        if len(rows)!=1:raise ValueError('Regional reduction did not return a single image/feature')
        value={}
        for band in row['context']['bands']:
            text=rows[0].get(band)
            value[band]=float(text) if text and math.isfinite(float(text)) else None
        return {'value':value}
    if action=='map_clear':record_event(account,{'type':'map_clear'});return {'value':True}
    catalog,items=catalog_snapshot()
    if action=='map_view':
        if 'center' in options:
            center=options['center']
            if not isinstance(center,list) or len(center)!=2 or not -180<=float(center[0])<=180 or not -90<=float(center[1])<=90:raise ValueError('Invalid map center')
            event={'type':'map_view','center':center}
        elif 'geometry' in options:
            geo=geometry(options['geometry'],catalog,items)
            from shapely.geometry import shape
            event={'type':'map_view','bounds':list(shape(geo).bounds)}
        else:raise ValueError('Map view needs center or geometry')
        if options.get('zoom') is not None:
            zoom=float(options['zoom'])
            if not 0<=zoom<=22:raise ValueError('zoom must be between 0 and 22')
            event['zoom']=zoom
        record_event(account,event);return {'value':True}
    if action not in {'evaluate','map','export_image','export_table'}:raise UnsupportedEEError('Unsupported EE action: '+str(action))
    compile_options={}
    if action.startswith('export_'):
        allowed={'description','folder','fileNamePrefix','fileFormat','selectors'}
        if action=='export_image':allowed|={'region','scale','crs','maxPixels'}
        unknown={k for k,v in options.items() if v is not None}-allowed
        if unknown:raise UnsupportedEEError('Unsupported export parameters: '+', '.join(sorted(unknown)))
        if options.get('region') is not None:
            export_region=geometry(options['region'],catalog,items)
            if export_region['type'] not in {'Polygon','MultiPolygon'}:
                raise UnsupportedEEError('Local image export region requires a Polygon or MultiPolygon')
            compile_options['region']=export_region
        for k in ['scale','crs']:
            if options.get(k) is not None:compile_options[k]=options[k]
    if action=='export_table':
        compiled=compile_expression(payload.get('expression'),catalog,items,compile_options,
                                    for_table_export=True)
    elif action=='evaluate':
        compiled=compile_expression(payload.get('expression'),catalog,items,compile_options,
                                    for_image_metadata=True)
    else:
        compiled=compile_expression(payload.get('expression'),catalog,items,compile_options)
    if any(node['process_id']=='local_ee_sample_regions' for node in compiled.get('process_graph',{}).values()):
        compiled['sample_budget']=sample_input_budget(compiled,items)
    if action=='export_table' and compiled['kind']=='value':
        header=table_columns(compiled['value'])
        selected=export_options(action,options,header)['selectors'] or header
        compiled={'kind':'table','bands':header,'warnings':compiled.get('warnings',[]),
                  'process_graph':table_input_graph(compiled['value'],selected)}
    if compiled['kind']=='region':
        grid=compiled['grid_options'];compiled['pixel_budget']=pixel_budget(compiled,items,grid,grid.get('maxPixels',10000000))
    elif compiled['kind'] in {'image','collection'} and action!='evaluate':
        if compiled['has_time_dimension']:raise UnsupportedEEError('A raster task requires a single Image; use first(), mosaic() or a collection reduction before export')
        compiled['pixel_budget']=pixel_budget(compiled,items,compile_options,options.get('maxPixels',100000000))
    if action=='evaluate':
        if compiled['kind']=='value':return compiled
        if compiled['kind'] in {'image','collection'}:
            # getInfo for an Image describes metadata; it does not return pixels.
            value={'type':'Image' if compiled['kind']=='image' else 'ImageCollection','bands':[{'id':b} for b in compiled['bands']],'properties':compiled.get('properties',{})}
            if compiled['kind']=='collection':value['features']=compiled.get('features',[{'type':'Image','id':i,'properties':{}} for i in compiled.get('source_item_ids',[])])
            return {'value':value,'warnings':compiled.get('warnings',[])}
        if compiled['kind']=='sample_table':
            result=make_job(backend,account,compiled,'GEE · 影像取样','CSV',ee_sample_results.result_context(compiled),True)
            return {**result,'pending':True}
        if compiled['kind'] in {'runtime_table','runtime_value','runtime_explanation'}:
            result=make_job(backend,account,compiled,'GEE · 分类评估','JSON',ee_runtime_results.result_context(compiled),True)
            return {**result,'pending':True}
        result=make_job(backend,account,compiled,'GEE · 区域统计','CSV',{'result_kind':'region'},True)
        return {**result,'pending':True}
    if compiled['kind'] not in {'image','collection','region','table','sample_table','runtime_table'}:raise UnsupportedEEError('This export requires a raster or supported feature table')
    if action=='map':
        if compiled['kind'] not in {'image','collection'}:raise UnsupportedEEError('Map.addLayer currently requires a raster')
        vis=visualization(options.get('vis_params') or {})
        opacity=options.get('opacity',1)
        if isinstance(opacity,bool) or not isinstance(opacity,(int,float)) or not 0<=opacity<=1:raise ValueError('opacity must be between 0 and 1')
        name=str(options.get('name','图层'))[:200]
        event={'type':'map_layer','job_id':'0'*36,'name':name,'vis_params':vis,'shown':bool(options.get('shown',True)),'opacity':opacity}
        check_event_capacity(account,event)
        result=make_job(backend,account,compiled,'地图 · '+name,'GTiff',{'result_kind':'map','vis_params':vis,'layer_name':name},False)
        event['job_id']=result['job_id']
        try:
            record_event(account,event)
            backend.batch_jobs.start_job(result['job_id'],User(account['user_id']))
        except Exception as error:
            try:
                backend.batch_jobs.cancel_job(result['job_id'],account['user_id'])
            except Exception as cleanup_error:
                error.add_note(f'Map child cancellation failed: {cleanup_error}')
            raise
        return result
    fmt=options.get('fileFormat','CSV' if action=='export_table' else 'GeoTIFF')
    formats={'GeoTIFF':'GTiff','GTiff':'GTiff','NetCDF':'NetCDF','CSV':'CSV'}
    if not isinstance(fmt,str) or fmt not in formats:raise UnsupportedEEError('Unsupported local export format: '+str(fmt))
    if action=='export_table' and compiled['kind'] not in {'region','table','sample_table','runtime_table'}:raise UnsupportedEEError('Only supported feature tables can currently be exported')
    if action=='export_image' and compiled['kind'] in {'sample_table','runtime_table'}:raise UnsupportedEEError('Use Export.table for feature tables')
    if action=='export_table' and fmt!='CSV':raise UnsupportedEEError('Local table export currently supports CSV')
    if action=='export_image' and formats[fmt]=='CSV':raise ValueError('Use Export.table for CSV')
    local_options=export_options(action,options,compiled['bands'])
    warnings=list(compiled.get('warnings',[]))
    warnings.append('toDrive 已适配为本地导出；没有向 Google Drive 传输数据。')
    if options.get('folder'):warnings.append('folder 仅记录为本地导出分组，不代表云端文件夹或宿主路径。')
    compiled['warnings']=warnings
    request_payload={'action':action,'expression':payload.get('expression'),'options':options} if request_id else None
    return make_job(backend,account,compiled,options.get('description') or 'GEE 本地导出',formats[fmt],{'result_kind':'export','export_group':str(options.get('folder',''))[:200],**local_options},False,request_id=request_id,request_payload=request_payload)
