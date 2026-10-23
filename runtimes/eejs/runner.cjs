'use strict';
const fs=require('node:fs');
const {send:sendRequest}=require('./bridge.cjs');
const util=require('node:util');
const path=require('node:path');
const NativeMap=global.Map;
global.window=globalThis;
const ee=require('./vendor/earthengine.cjs');
global.ee=ee;
const raw=JSON.parse(fs.readFileSync(path.join(__dirname,'vendor/algorithms.json'),'utf8')).algorithms;
const signatures=Object.fromEntries(raw.map(a=>[a.name.replace(/^algorithms\//,''),{description:a.description,returns:a.returnType,args:(a.arguments||[]).map(x=>({name:x.argumentName,type:x.type,optional:!!x.optional,description:x.description,...('defaultValue' in x?{default:x.defaultValue}:{})}))}]));
ee.data.getAlgorithms=callback=>callback?callback(signatures):signatures;
// The browser distribution has no Node OAuth dependencies. All supported I/O is routed locally.
ee.initialize('http://api:8080/gee/v1/unsupported','http://api:8080/gee/v1/unsupported');
function send(payload){
  const value=sendRequest(payload);
  for(const warning of value.warnings||[])console.warn('[兼容提示]',warning);
  return value;
}
const encode=object=>ee.Serializer.encode(object);
ee.data.computeValue=(object,callback)=>{
  try{const result=send({action:'evaluate',expression:encode(object)}).value;if(callback){queueMicrotask(()=>callback(result));return;}return result;}
  catch(error){if(callback){queueMicrotask(()=>callback(undefined,error.message));return;}throw error;}
};
const printable=value=>value instanceof ee.ComputedObject?value.getInfo():value;
global.print=(...args)=>console.log(...args.map(value=>util.inspect(printable(value),{colors:false,depth:5,maxArrayLength:40,maxStringLength:8000})));
function geometry(value){
  if(!value)return undefined;
  const object=value instanceof ee.FeatureCollection||value instanceof ee.Feature||value instanceof ee.Image||value instanceof ee.ImageCollection?value.geometry():value;
  return object instanceof ee.ComputedObject?encode(object):object;
}
function task(response){return Object.freeze({id:response.job_id,start(){send({action:'start',job_id:response.job_id});return this;},status(){return send({action:'status',job_id:response.job_id}).value;},toString(){return `Local export task ${response.job_id}`;}});}
function exportImage(...args){
  const names=['image','description','folder','fileNamePrefix','dimensions','region','scale','crs','crsTransform','maxPixels','shardSize','fileDimensions','skipEmptyTiles','fileFormat','formatOptions','priority'];
  const options=args[0] instanceof ee.ComputedObject?Object.fromEntries(names.map((n,i)=>[n,args[i]]).filter(x=>x[1]!==undefined)):{...args[0]};
  if(!options.image)throw Error('Export.image.toDrive requires image');
  const image=options.image;delete options.image;
  if(options.region)options.region=geometry(options.region);
  const response=send({action:'export_image',expression:encode(image),options});
  console.log('本地导出任务已创建，点击任务面板“开始导出”:',response.job_id);
  return task(response);
}
function exportTable(...args){
  const names=['collection','description','folder','fileNamePrefix','fileFormat','selectors','maxVertices','priority'];
  const options=args[0] instanceof ee.ComputedObject?Object.fromEntries(names.map((n,i)=>[n,args[i]]).filter(x=>x[1]!==undefined)):{...args[0]};
  const collection=options.collection;delete options.collection;
  if(!collection)throw Error('Export.table.toDrive requires collection');
  const response=send({action:'export_table',expression:encode(collection),options});
  console.log('本地表格导出任务已创建:',response.job_id);return task(response);
}
global.Export=Object.freeze({image:Object.freeze({toDrive:exportImage,toCloudStorage(){throw Error('Cloud Storage is unavailable; use local toDrive exports');},toAsset(){throw Error('Export.image.toAsset is not implemented; export a local GeoTIFF first');}}),table:Object.freeze({toDrive:exportTable,toAsset(){throw Error('Export.table.toAsset is not implemented');}})});
function LocalMap(...args){return new NativeMap(...args);}
Object.assign(LocalMap,{
  addLayer(object,visParams={},name='图层',shown=true,opacity=1){
    if(object instanceof ee.ImageCollection)object=object.mosaic();
    if(visParams.bands)object=ee.Image(object).select(typeof visParams.bands==='string'?visParams.bands.split(','):visParams.bands);
    const response=send({action:'map',expression:encode(object),options:{vis_params:visParams,name,shown,opacity}});
    console.log(`地图计算已排队: ${name} (${response.job_id})`);return response.job_id;
  },
  centerObject(object,zoom){send({action:'map_view',options:{geometry:geometry(object),zoom}});},
  setCenter(lon,lat,zoom){send({action:'map_view',options:{center:[lon,lat],zoom}});},
  setOptions(type){if(!['SATELLITE','HYBRID','ROADMAP','TERRAIN'].includes(type))throw Error('Unknown map option');console.warn('使用本地底图；未连接外部卫星底图服务。');},
  clear(){send({action:'map_clear'});},
  setControlVisibility(){console.warn('Map.setControlVisibility is managed by the local workbench.');},
});
global.Map=LocalMap;
// Explicitly fail unsupported Google network functions rather than falling through to external services.
for(const name of ['authenticate','authenticateViaOauth','authenticateViaPrivateKey','setAuthToken'])if(ee.data[name])ee.data[name]=()=>{throw Error('Google authentication is disabled in the local runtime');};
const source=process.argv[2]||'/job/script.js';
const text=fs.readFileSync(source,'utf8');
// Execute JavaScript inside the supervised native OS sandbox process.
const Module=require('node:module');const script=new Module(source,module);script.filename=source;script.paths=[];
try{script._compile(text,source);}catch(error){console.error(error.stack||error.message);process.exitCode=1;}
