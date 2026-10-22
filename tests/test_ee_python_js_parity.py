"""Shared compiler regressions from both unmodified, pinned SDK serializers."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Parity fixture attempted networking'); }
for (const module of ['node:http', 'node:https']) {
  const api = require(module); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny;
global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
global.ee = ee;
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const c = ee.ImageCollection('sentinel-2-l2a');
const joined = ee.ImageCollection(ee.Join.saveFirst('match').apply(
  c, c, ee.Filter.equals({leftField:'system:index', rightField:'system:index'})));
const best = ee.ImageCollection(ee.Join.saveBest('match', 'delta').apply(
  c, c, ee.Filter.maxDifference({difference:1000,
    leftField:'system:time_start', rightField:'system:time_start'})));
const rows = ee.FeatureCollection([0,1,2].map(x =>
  ee.Feature(null, {constant:1, x:x, y:1 + 2*x})));
const inner = ee.ImageCollection(ee.Join.inner().apply(c, c,
  ee.Filter.equals({leftField:'system:index', rightField:'system:index'})).map(f =>
  ee.Image(ee.Feature(f).get('primary')).select('red').addBands(
    ee.Image(ee.Feature(f).get('secondary')).select('nir'))));
const prior = ee.ImageCollection(ee.Join.saveBest('match', 'delta').apply(c, c,
  ee.Filter.and(ee.Filter.maxDifference({difference:172800000,
    leftField:'system:time_start', rightField:'system:time_start'}),
    ee.Filter.greaterThan({leftField:'system:time_start', rightField:'system:time_start'}))));
const values = {
  listLayout: ee.List.repeat(2,3).zip([10,20]).unzip().flatten().reverse().swap(0,-1).set(1,99),
  listRegression: ee.Dictionary(ee.List([[1,0,1],[1,1,2],[1,2,6],[1,3,7]])
    .reduce(ee.Reducer.linearRegression(2,1))).get('coefficients'),
  listMean: ee.List([1,null,3]).reduce(ee.Reducer.mean()),
  confusionKappa: ee.ConfusionMatrix(ee.Array([[5,1,0],[2,3,1],[0,1,4]])).kappa(),
  labelErrorMatrix: ee.FeatureCollection([[10,20],[20,20],[20,20],[20,10],[20,10],[20,10]]
    .map(pair => ee.Feature(null,{truth:pair[0],pred:pair[1]})))
    .errorMatrix('truth','pred',[20,10]).array(),
  rasterLinearFit: c.select(['red','nir']).reduce(ee.Reducer.linearFit()),
  rasterProjection: ee.Image(ee.Array([[1,2],[3,4]])).matrixMultiply(
    c.first().select(['red','nir']).toArray().toArray(1))
    .arrayProject([0]).arrayFlatten([['p1','p2']]),
  rasterReduction: c.first().select(['red','nir']).toArray()
    .arrayReduce(ee.Reducer.mean(),[0]).arrayFlatten([['mean']]),
  arrayLayout: ee.Array([[1,2,3]]).repeat(0,2).slice(1,-2).reduce(ee.Reducer.sum(),[0]).project([1]),
  arrayEigen: ee.Array([[4,1],[1,3]]).eigen(),
  arrayCholesky: ee.Array([[4,12],[12,37]]).matrixCholeskyDecomposition(),
  arrayArithmetic: ee.Array([1,4,9]).sqrt().multiply(ee.Array([2,3,4])).accum(0),
  sequence: ee.List.sequence(0, 1, 99, 5),
  emptyKeys: ee.Dictionary({a:1}).values([]),
  missingDefault: ee.Dictionary({a:1}).get('missing', false),
  matrixMultiply: ee.Array([[1,2],[3,4]]).matrixMultiply([[1],[1]]),
  matrixSolve: ee.Array([[1,0],[1,1],[1,2]]).matrixSolve([[1],[3],[5]]),
  notNull: c.filter(ee.Filter.notNull(['cloud'])).size(),
  matchId: ee.Image(ee.Image(joined.first()).get('match')).get('system:index'),
  bestDelta: ee.Image(ee.Image(best.first()).get('match')).get('delta'),
  tableCoefficients: rows.reduceColumns(ee.Reducer.linearRegression(2, 1),
    ['constant','x','y']).get('coefficients'),
  featureSum: rows.filter(ee.Filter.gt('x', 0)).iterate((feature, previous) =>
    ee.Number(previous).add(ee.Feature(feature).get('y')), 0),
  formatted: ee.Number(7).divide(2).format('%.2f'),
  stringConversion: ee.String(ee.Number(42)).cat(' units'),
  innerBands: inner.first().bandNames(),
  compoundDelta: ee.Image(prior.first().get('match')).get('delta'),
  clippedBands: c.first().clip(ee.Geometry.Rectangle([100.1,30.1,100.9,30.9],null,false)).bandNames()
};
const expressions = Object.fromEntries(Object.entries(values).map(([k,v]) => [k,ee.Serializer.encode(v)]));
if (attempts !== 0) throw Error('SDK swallowed a network attempt');
console.log(JSON.stringify(expressions));
"""


@pytest.fixture(scope="module")
def parity_values():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for live official JavaScript serializer parity")
    result = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    js = json.loads(result.stdout)
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    c = ee.ImageCollection("sentinel-2-l2a")
    joined = ee.ImageCollection(ee.Join.saveFirst("match").apply(
        c, c, ee.Filter.equals(leftField="system:index", rightField="system:index")))
    best = ee.ImageCollection(ee.Join.saveBest("match", "delta").apply(
        c, c, ee.Filter.maxDifference(difference=1000,
                                     leftField="system:time_start", rightField="system:time_start")))
    rows = ee.FeatureCollection([ee.Feature(None, {"constant": 1, "x": x, "y": 1 + 2*x})
                                 for x in range(3)])
    inner = ee.ImageCollection(ee.Join.inner().apply(c, c,
        ee.Filter.equals(leftField="system:index", rightField="system:index")).map(
        lambda f: ee.Image(ee.Feature(f).get("primary")).select("red").addBands(
            ee.Image(ee.Feature(f).get("secondary")).select("nir"))))
    prior = ee.ImageCollection(ee.Join.saveBest("match", "delta").apply(c, c,
        ee.Filter.And(ee.Filter.maxDifference(difference=172800000,
            leftField="system:time_start", rightField="system:time_start"),
            ee.Filter.greaterThan(leftField="system:time_start", rightField="system:time_start"))))
    py = {
        "listLayout": ee.List.repeat(2, 3).zip([10, 20]).unzip().flatten().reverse().swap(0, -1).set(1, 99),
        "listRegression": ee.Dictionary(ee.List([[1, 0, 1], [1, 1, 2], [1, 2, 6], [1, 3, 7]])
            .reduce(ee.Reducer.linearRegression(2, 1))).get('coefficients'),
        "listMean": ee.List([1, None, 3]).reduce(ee.Reducer.mean()),
        "confusionKappa": ee.ConfusionMatrix(ee.Array([[5,1,0],[2,3,1],[0,1,4]])).kappa(),
        "labelErrorMatrix": ee.FeatureCollection([ee.Feature(None,{"truth":a,"pred":b})
            for a,b in [[10,20],[20,20],[20,20],[20,10],[20,10],[20,10]]])
            .errorMatrix("truth","pred",[20,10]).array(),
        "rasterLinearFit": c.select(["red","nir"]).reduce(ee.Reducer.linearFit()),
        "rasterProjection": ee.Image(ee.Array([[1,2],[3,4]])).matrixMultiply(
            c.first().select(["red","nir"]).toArray().toArray(1))
            .arrayProject([0]).arrayFlatten([["p1","p2"]]),
        "rasterReduction": c.first().select(["red","nir"]).toArray()
            .arrayReduce(ee.Reducer.mean(),[0]).arrayFlatten([["mean"]]),
        "arrayLayout": ee.Array([[1,2,3]]).repeat(0,2).slice(1,-2).reduce(ee.Reducer.sum(),[0]).project([1]),
        "arrayEigen": ee.Array([[4,1],[1,3]]).eigen(),
        "arrayCholesky": ee.Array([[4,12],[12,37]]).matrixCholeskyDecomposition(),
        "arrayArithmetic": ee.Array([1,4,9]).sqrt().multiply(ee.Array([2,3,4])).accum(0),
        "sequence": ee.List.sequence(0, 1, 99, 5),
        "emptyKeys": ee.Dictionary({"a": 1}).values([]),
        "missingDefault": ee.Dictionary({"a": 1}).get("missing", False),
        "matrixMultiply": ee.Array([[1, 2], [3, 4]]).matrixMultiply([[1], [1]]),
        "matrixSolve": ee.Array([[1, 0], [1, 1], [1, 2]]).matrixSolve([[1], [3], [5]]),
        "notNull": c.filter(ee.Filter.notNull(["cloud"])).size(),
        "matchId": ee.Image(ee.Image(joined.first()).get("match")).get("system:index"),
        "bestDelta": ee.Image(ee.Image(best.first()).get("match")).get("delta"),
        "tableCoefficients": rows.reduceColumns(ee.Reducer.linearRegression(2, 1),
                                                 ["constant", "x", "y"]).get("coefficients"),
        "featureSum": rows.filter(ee.Filter.gt("x", 0)).iterate(
            lambda feature, previous: ee.Number(previous).add(ee.Feature(feature).get("y")), 0),
        "formatted": ee.Number(7).divide(2).format("%.2f"),
        "stringConversion": ee.String(ee.Number(42)).cat(" units"),
        "innerBands": inner.first().bandNames(),
        "compoundDelta": ee.Image(prior.first().get("match")).get("delta"),
        "clippedBands": c.first().clip(ee.Geometry.Rectangle(
            [100.1, 30.1, 100.9, 30.9], proj="EPSG:4326", geodesic=False)).bandNames(),
    }
    metadata, items, _ = synthetic_inputs()
    return js, {key: ee.serializer.encode(value, for_cloud_api=False)
                for key, value in py.items()}, [metadata], items


@pytest.mark.parametrize("case", ["sequence", "emptyKeys", "missingDefault", "matrixMultiply",
                                 "matrixSolve", "notNull", "matchId", "clippedBands",
                                 "bestDelta", "tableCoefficients", "featureSum", "formatted",
                                 "stringConversion", "innerBands", "compoundDelta",
                                 "arrayLayout", "arrayEigen", "arrayCholesky", "arrayArithmetic",
                                 "rasterProjection", "rasterReduction", "rasterLinearFit",
                                 "confusionKappa", "labelErrorMatrix",
                                 "listLayout", "listRegression", "listMean"])
def test_python_and_javascript_reach_the_same_local_result(parity_values, case):
    javascript, python, metadata, items = parity_values
    left = compile_expression(javascript[case], metadata, items)
    right = compile_expression(python[case], metadata, items)
    assert left == right
    assert left["kind"] == ("image" if case.startswith("raster") else "value")
