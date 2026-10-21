/* Independently authored minimal probes for the cited public workflows.
 * Uses the pinned official SDK offline. Does not execute downloaded scripts,
 * access Google, submit jobs or claim numerical equivalence.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
global.window = globalThis;
const ee = require(path.join(root, 'vendor/earthengine-js/earthengine.cjs'));
global.ee = ee;
const algorithms = JSON.parse(fs.readFileSync(path.join(root, 'vendor/earthengine-js/algorithms.json'))).algorithms;
const signatures = Object.fromEntries(algorithms.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name:x.argumentName,type:x.type,optional:!!x.optional,
    description:x.description,...('defaultValue' in x ? {default:x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = () => {throw Error('Audit must not call a server');};
const c = ee.ImageCollection('sentinel-2-l2a');
const im = ee.Image(c.first());
const n = im.select('nir');
const roi = ee.Geometry.Rectangle([0,0,2,2], null, false);
const training = ee.FeatureCollection([ee.Feature(roi, {class:1, nir:0.7, red:0.2})]);
const tests = [
  ['control_ndvi_median','control',()=>c.map(x=>x.normalizedDifference(['nir','red']).rename('NDVI')).median().clip(roi)],
  ['control_scl_mask','control',()=>c.map(x=>x.updateMask(x.select('SCL').neq(6)).select('nir')).mean()],
  ['control_explicit_dates','control',()=>ee.ImageCollection.fromImages(c.toList(3)).map(x=>x.set('year',x.date().get('year'))).aggregate_array('year')],
  ['quality_mosaic','quality_mosaic',()=>c.qualityMosaic('nir')],
  ['qa_bitwise_and','harmonic,classification,landtrendr',()=>n.bitwiseAnd(31)],
  ['qa_right_shift','cloud_masks',()=>n.rightShift(2)],
  ['unmask','landtrendr',()=>n.unmask(0)],
  ['integer_int16','histarfm,landtrendr',()=>n.int16()],
  ['date_difference','harmonic,histarfm,arrays',()=>ee.Date('2024-02-01').difference(ee.Date('2024-01-01'),'day')],
  ['date_get_relative','histarfm',()=>ee.Date('2024-02-01').getRelative('day','year')],
  ['mapped_image_date','harmonic,arrays',()=>c.map(x=>x.addBands(ee.Image(x.date().millis()).rename('t')))],
  ['standalone_constant_grid','histarfm',()=>ee.Image.constant(1)],
  ['join_save_first','s2cloudless',()=>ee.Join.saveFirst('cloud').apply(c,c,ee.Filter.equals({leftField:'system:index',rightField:'system:index'}))],
  ['join_save_all','histarfm',()=>ee.Join.saveAll('matches').apply(c,c,ee.Filter.equals({leftField:'system:index',rightField:'system:index'}))],
  ['filter_max_difference','histarfm',()=>c.filter(ee.Filter.maxDifference({difference:86400000,leftField:'system:time_start',rightField:'system:time_start'}))],
  ['focal_min','s2cloudless',()=>n.focalMin(2)],
  ['focal_max','s2cloudless',()=>n.focalMax(2)],
  ['directional_distance','s2cloudless',()=>n.directionalDistanceTransform(90,10)],
  ['image_reproject','s2cloudless',()=>n.reproject({crs:'EPSG:32649',scale:20})],
  ['image_projection','s2cloudless',()=>n.projection()],
  ['neighborhood_mean','spatial',()=>n.reduceNeighborhood({reducer:ee.Reducer.mean(),kernel:ee.Kernel.square(1)})],
  ['linear_regression','harmonic',()=>c.select(['red','nir']).reduce(ee.Reducer.linearRegression(1,1))],
  ['linear_fit','time_series',()=>c.select(['red','nir']).reduce(ee.Reducer.linearFit())],
  ['to_array','arrays',()=>c.select(['red','nir']).toArray()],
  ['image_to_array','arrays',()=>im.select(['red','nir']).toArray()],
  // Placeholder Image inputs isolate the missing handler, not array validity.
  ['array_slice','arrays,landtrendr',()=>im.arraySlice(0,0,2)],
  ['array_project','harmonic,arrays,landtrendr',()=>im.arrayProject([0])],
  ['array_flatten','harmonic,arrays,landtrendr',()=>im.arrayFlatten([['x','y']])],
  ['matrix_solve','arrays',()=>im.matrixSolve(im)],
  ['image_atan2','harmonic',()=>n.atan2(im.select('red'))],
  ['image_hypot','harmonic',()=>n.hypot(im.select('red'))],
  ['hsv_to_rgb','harmonic',()=>im.select(['red','green','blue']).hsvToRgb()],
  ['reducer_percentile','statistics',()=>c.select('nir').reduce(ee.Reducer.percentile([5,50,95]))],
  ['reducer_histogram','statistics',()=>n.reduceRegion({reducer:ee.Reducer.histogram(),geometry:roi,scale:10})],
  ['reducer_combined','statistics',()=>n.reduceRegion({reducer:ee.Reducer.mean().combine({reducer2:ee.Reducer.sampleStdDev(),sharedInputs:true}),geometry:roi,scale:10})],
  ['multi_region_statistics','classification',()=>n.reduceRegions({collection:training,reducer:ee.Reducer.mean(),scale:10})],
  ['sample_regions','classification',()=>im.sampleRegions({collection:training,properties:['class'],scale:10})],
  ['sample_random','classification',()=>im.sample({region:roi,scale:10,numPixels:100,seed:0})],
  ['stratified_sample','classification',()=>im.stratifiedSample({numPoints:10,classBand:'SCL',region:roi,scale:10})],
  ['random_forest_constructor','classification',()=>ee.Classifier.smileRandomForest(10)],
  ['random_forest_train','classification',()=>ee.Classifier.smileRandomForest(10).train(training,'class',['nir','red'])],
  ['image_classify','classification',()=>im.classify(ee.Classifier.smileRandomForest(10).train(training,'class',['nir','red']))],
  ['confusion_matrix','classification',()=>ee.Classifier.smileRandomForest(10).train(training,'class',['nir','red']).confusionMatrix()],
  ['landtrendr','landtrendr',()=>ee.Algorithms.TemporalSegmentation.LandTrendr({timeSeries:c.select('nir'),maxSegments:6})],
  ['connected_pixels','landtrendr',()=>n.connectedPixelCount(100,true)],
  ['collection_iterate','time_series',()=>c.iterate((x,previous)=>ee.Image(previous).add(ee.Image(x).select('nir')),n)],
  ['landsat_load','data',()=>ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').size()],
  ['cloud_probability_load','data',()=>ee.ImageCollection('COPERNICUS/S2_CLOUD_PROBABILITY').size()],
  ['unavailable_qa60','data',()=>ee.Image(ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').first()).select('QA60')],
  ['unavailable_swir','data',()=>ee.Image(ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').first()).select('B11')],
  ['scale_graph_one_band','scale',()=>c.select('nir').mean()],
  ['scale_graph_two_bands','scale',()=>c.select(['nir','red']).mean()],
];
const result = tests.map(([id,workflow,make])=>{
  try {return {id,workflow,sdk_serialized:true,expression:ee.Serializer.encode(make())};}
  catch(error) {return {id,workflow,sdk_serialized:false,error:String(error.message)};}
});
process.stdout.write(JSON.stringify(result,null,2)+'\n');
