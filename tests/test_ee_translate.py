"""Offline EE compilation contracts and independent NumPy process evaluation."""
import copy
import json
from pathlib import Path
import warnings

import numpy as np
import pytest

from gee.ee_translate import UnsupportedEEError, compile_expression


def call(name, **args):
    return {"type": "Invocation", "functionName": name, "arguments": args}


def col(): return call("ImageCollection.load", id="sentinel-2-l2a")


def first(): return call("Collection.first", collection=col())


def select(image, *names): return call("Image.select", input=image, bandSelectors=list(names))


def rect(w=0, s=0, e=2, n=2):
    return {"type": "Polygon", "coordinates": [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}


@pytest.fixture
def local():
    names = ["blue", "green", "red", "nir", "SCL"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": names}}}]
    items = {"sentinel-2-l2a": [
        {"id": "a", "bbox": [0,0,2,2], "geometry": rect(), "properties": {"system:time_start": 1000, "system:index": "a", "CLOUDY_PIXEL_PERCENTAGE": 20}},
        {"id": "b", "bbox": [1,0,3,2], "geometry": rect(1,0,3,2), "properties": {"system:time_start": 1001, "system:index": "b", "CLOUDY_PIXEL_PERCENTAGE": 5}},
        {"id": "c", "bbox": [10,0,12,2], "geometry": rect(10,0,12,2), "properties": {"system:time_start": 2000, "system:index": "c", "CLOUDY_PIXEL_PERCENTAGE": 90}}]}
    return catalog, items


def compile(value, local, **opts): return compile_expression(value, *local, options=opts or None)


def processes(result):
    return [n["process_id"] for n in result["process_graph"].values()]


def loads(result):
    return [n["arguments"] for n in result["process_graph"].values() if n["process_id"] == "load_collection"]


def eval_process(process, args):
    """Small independent evaluator, for semantic fixtures, not an execution path."""
    if process == "array_element": return args["data"][int(args["index"])]
    x, y = args.get("x"), args.get("y")
    if process == "add": return x+y
    if process == "subtract": return x-y
    if process == "multiply": return x*y
    if process == "divide":
        with np.errstate(divide="ignore", invalid="ignore"):
            return x/y
    if process == "power": return args["base"]**args["p"]
    if process == "exp": return np.exp(args["p"])
    if process == "log": return np.log(x)/np.log(args["base"])
    if process == "sqrt": return np.sqrt(x)
    if process == "absolute": return np.abs(x)
    if process == "gt": return x>y
    if process == "gte": return x>=y
    if process == "lt": return x<y
    if process == "lte": return x<=y
    if process == "eq": return x==y
    if process == "neq": return x!=y
    if process == "and": return np.logical_and(x,y)
    if process == "or": return np.logical_or(x,y)
    if process == "not": return np.logical_not(x)
    if process == "is_nodata": return np.isnan(x)
    if process == "if":
        return np.where(args["value"], np.nan if args["accept"] is None else args["accept"], np.nan if args["reject"] is None else args["reject"])
    data = np.stack(np.broadcast_arrays(*args["data"])).astype(float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        if process == "mean": return np.nanmean(data, axis=0)
        if process == "median": return np.nanmedian(data, axis=0)
        if process == "sd": return np.nanstd(data, axis=0, ddof=1)
        if process == "min": return (np.nanmin if args.get("ignore_nodata", True) else np.min)(data, axis=0)
        if process == "max": return (np.nanmax if args.get("ignore_nodata", True) else np.max)(data, axis=0)
        if process == "sum": return np.where(np.isfinite(data).any(axis=0), np.nansum(data, axis=0), np.nan)
        if process == "count": return np.isfinite(data).sum(axis=0)
        if process in {"first", "last"}:
            if process == "last": data = data[::-1]
            return np.take_along_axis(data, np.argmax(np.isfinite(data),axis=0)[None,...], axis=0)[0]
    raise AssertionError(process)


def callback(graph, parameters):
    values = {}
    def resolve(v):
        if isinstance(v, dict):
            if "from_parameter" in v: return parameters[v["from_parameter"]]
            if "from_node" in v: return values[v["from_node"]]
            return {k:resolve(x) for k,x in v.items()}
        if isinstance(v, list): return [resolve(x) for x in v]
        return v
    for key, node in graph.items():
        values[key] = eval_process(node["process_id"], resolve(node["arguments"]))
        if node.get("result"): out = values[key]
    return out


def evaluate_graph(result, arrays, grid=None, source_geometries=None,
                   process_handlers=None):
    """Independent sample-vector reference; grid gives mask sample centers.

    Rasters have [time,band,pixel] axes until time is reduced. With grid, source
    extents and optional per-item geometries mask the supplied sample values.
    Point masks do not establish native/fractional-boundary raster acceptance.
    Optional process_handlers are test-only numerical oracles keyed by process
    id; they do not execute a native process or change the default evaluator.
    """
    def positions_for(data):
        positions = np.asarray(grid, dtype=float)
        if positions.shape != (data.shape[-1], 2) or not np.isfinite(positions).all():
            raise AssertionError("Spatial reference needs one finite grid center per sample")
        return positions

    def polygon_mask(geometry, positions):
        from shapely.geometry import Point, shape

        polygon = shape(geometry)
        return np.array([polygon.covers(Point(*position)) for position in positions])

    if source_geometries is not None and grid is None:
        raise AssertionError("Per-item source geometries require sample grid centers")
    values = {}
    for key, node in result["process_graph"].items():
        p, a = node["process_id"], node["arguments"]
        def cube(ref): return values[ref["from_node"]]
        if p == "load_collection":
            # GeoTrellis time-axis iteration is chronological, independent of
            # the STAC link order. Compiler chooses first/last accordingly.
            ids = sorted(a["_gee_item_ids"])
            data = np.stack([np.stack([arrays[i][b] for b in a["bands"]]) for i in ids])
            if grid is not None:
                positions = positions_for(data)
                extent = a["spatial_extent"]
                inside = ((positions[:,0] >= extent["west"]) & (positions[:,0] <= extent["east"])
                          & (positions[:,1] >= extent["south"]) & (positions[:,1] <= extent["north"]))
                data = np.where(inside, data, np.nan)
                if source_geometries is not None:
                    masks = np.stack([polygon_mask(source_geometries[i], positions) for i in ids])
                    data = np.where(masks[:,None,:], data, np.nan)
            v = (data, a["bands"], True)
        elif p == "filter_bands":
            data,names,timed = cube(a["data"])
            axis = 1 if timed else 0
            v = (np.take(data,[names.index(n) for n in a["bands"]],axis=axis),a["bands"],timed)
        elif p == "rename_labels":
            data,names,timed = cube(a["data"]); v = (data,a["target"],timed)
        elif p == "merge_cubes":
            x,nx,timed = cube(a["cube1"]); y,ny,t2 = cube(a["cube2"])
            assert timed == t2
            assert not set(nx)&set(ny)
            v = (np.concatenate([x,y],axis=1 if timed else 0),nx+ny,timed)
        elif p == "reduce_dimension":
            data,names,timed = cube(a["data"])
            axis = 0 if a["dimension"] == "t" else 1 if timed else 0
            out = callback(a["reducer"]["process_graph"], {"data": np.moveaxis(data,axis,0)})
            v = (out,names if a["dimension"]=="t" else [],False if a["dimension"]=="t" else timed)
        elif p == "add_dimension":
            data,names,timed = cube(a["data"])
            v = (np.expand_dims(data,1 if timed else 0),[a["label"]],timed)
        elif p == "apply":
            data,names,timed = cube(a["data"])
            v = (callback(a["process"]["process_graph"],{"x":data}),names,timed)
        elif p == "mask":
            data,names,timed=cube(a['data']); mask,_,_=cube(a['mask'])
            v=(np.where(mask,np.nan,data),names,timed)
        elif p == "local_ee_constant_on_grid":
            data,names,timed = cube(a["data"])
            # A constant's validity is independent of template NoData; the
            # separate polygon process supplies its physical footprint.
            v = (np.full(data.shape, a["value"], dtype=np.float64), names, timed)
        elif p in {"local_ee_to_float", "local_ee_to_double"}:
            data,names,timed = cube(a["data"])
            dtype = np.float32 if p == "local_ee_to_float" else np.float64
            v = (data.astype(dtype).astype(np.float64), names, timed)
        elif p == "mask_polygon":
            data,names,timed = cube(a["data"])
            inside = polygon_mask(a["mask"], positions_for(data))
            v = (np.where(inside, data, np.nan), names, timed)
        elif process_handlers is not None and p in process_handlers:
            v = process_handlers[p](a, values)
        else: raise AssertionError(p)
        values[key] = v
        if node.get("result"): result_value = v
    return result_value


@pytest.fixture
def arrays():
    return {i: {"blue": np.array([.1,.2]), "green": np.array([.2,.4]), "red": np.array([1.,3.]),
                "nir": np.array([n,np.nan if i=="b" else 3.]), "SCL": np.array([4.,6.])}
            for i,n in [("a",1.),("b",9.),("c",5.)]}


def test_millisecond_date_and_single_argument(local):
    for end, expected in [(1001,["a"]),(1002,["a","b"])]:
        f = call("Filter.dateRangeContains",rightField="system:time_start",leftValue=call("DateRange",start=1000,end=end))
        r=compile(call("Collection.filter",collection=col(),filter=f),local)
        assert loads(r)[0]["_gee_item_ids"]==expected
        assert "filter_temporal" not in processes(r)
    f=call("Filter.dateRangeContains",rightField="system:time_start",leftValue=call("DateRange",start=1000))
    assert loads(compile(call("Collection.filter",collection=col(),filter=f),local))[0]["_gee_item_ids"]==["a"]


def test_filter_bounds_does_not_clip(local):
    f=call("Filter.intersects",leftField=".all",rightValue=call("Feature",geometry=rect(1,1,1.5,1.5)))
    r=compile(call("Collection.filter",collection=col(),filter=f),local)
    assert loads(r)[0]["_gee_item_ids"]==["a","b"]
    assert loads(r)[0]["spatial_extent"]==dict(west=0,south=0,east=3,north=2)
    assert "mask_polygon" not in processes(r)
    clipped=compile(call("Image.clip",input=first(),geometry=rect(.5,.5,1,1)),local)
    assert "mask_polygon" in processes(clipped)


def test_metadata_filter_sort_limit_and_missing(local):
    filt=call("Filter.not",filter=call("Filter.greaterThan",leftField="CLOUDY_PIXEL_PERCENTAGE",rightValue=50))
    c=call("Collection.filter",collection=col(),filter=filt)
    c=call("Collection.limit",collection=c,key="CLOUDY_PIXEL_PERCENTAGE",ascending=True,limit=1)
    assert loads(compile(c,local))[0]["_gee_item_ids"]==["b"]
    assert compile(call("Collection.size",collection=c),local)["value"]==1
    with pytest.raises(UnsupportedEEError,match="unavailable"):
        compile(call("Collection.filter",collection=col(),filter=call("Filter.lessThan",leftField="QA60",rightValue=20)),local)


def test_median_mosaic_and_reverse_are_distinct(local,arrays):
    c=call("Collection.limit",collection=col(),limit=2)
    c=call("Collection.map",collection=c,baseAlgorithm={"type":"Function","argumentNames":["im"],"body":select({"type":"ArgumentRef","value":"im"},"nir")})
    med=compile(call("reduce.median",collection=c),local)
    mosaic=compile(call("ImageCollection.mosaic",collection=c),local)
    np.testing.assert_allclose(evaluate_graph(med,arrays)[0],[[5,3]])
    np.testing.assert_allclose(evaluate_graph(mosaic,arrays)[0],[[9,3]])
    reverse=call("Collection.limit",collection=c,key="system:time_start",ascending=False)
    r=compile(call("ImageCollection.mosaic",collection=reverse),local)
    np.testing.assert_allclose(evaluate_graph(r,arrays)[0],[[1,3]])
    same=copy.deepcopy(local);same[1]["sentinel-2-l2a"][1]["properties"]["system:time_start"]=1000
    np.testing.assert_allclose(evaluate_graph(compile(call("ImageCollection.mosaic",collection=c),same),arrays)[0],[[9,3]])


def test_select_rename_missing_and_addbands(local):
    r=compile(call("Image.select",input=first(),bandSelectors=["nir","red"],newNames=["N","R"]),local)
    assert r["bands"]==["N","R"]
    assert compile(select(first(),"r.*"),local)["bands"]==["red"]
    assert compile(select(first(),3,2),local)["bands"]==["nir","red"]
    with pytest.raises(UnsupportedEEError,match="did not match"): compile(select(first(),"QA60"),local)
    with pytest.raises(UnsupportedEEError,match="band count"):
        compile(call("Image.rename",input=first(),names=["x"]),local)
    base=select(first(),"nir")
    appended=call("Image.addBands",dstImg=base,srcImg=base)
    assert compile(call("Image.addBands",dstImg=appended,srcImg=base),local)["bands"]==["nir","nir_1","nir_2"]
    assert compile(call("Image.addBands",dstImg=base,srcImg=base,overwrite=True),local)["bands"]==["nir"]


def expression(text, image=None, **variables):
    parser=call("Image.parseExpression",expression=text,argName="DEFAULT_EXPRESSION_IMAGE",vars=["DEFAULT_EXPRESSION_IMAGE",*variables])
    return {"type":"CompoundValue","scope":[["parse",parser]],"value":{"type":"Invocation","function":{"type":"ValueRef","value":"parse"},"arguments":{"DEFAULT_EXPRESSION_IMAGE": image or first(),**variables}}}


def test_negative_nd_vs_expression_and_properties(local,arrays):
    arrays["a"]["nir"]=np.array([-1.,0.]); arrays["a"]["red"]=np.array([3.,0.])
    nd=compile(call("Image.normalizedDifference",input=first(),bandNames=["nir","red"]),local)
    assert nd["bands"]==["nd"] and nd["properties"]=={}
    assert np.isnan(evaluate_graph(nd,arrays)[0]).all()
    ex=compile(expression('index = (b("nir") - b("red")) / (b("nir") + b("red"))'),local)
    assert ex["bands"]==["index"]
    with np.errstate(divide="ignore",invalid="ignore"):
        assert evaluate_graph(ex,arrays)[0][0,0]==-2


def test_binary_mask_direction_and_no_resurrection(local,arrays):
    arrays["a"]["nir"]=np.array([10.,np.nan]);arrays["a"]["red"]=np.array([1.,0.])
    im=select(first(),"nir")
    mask=call("Image.eq",image1=select(first(),"red"),image2=call("Image.constant",value=1))
    r=compile(call("Image.updateMask",image=im,mask=mask),local)
    np.testing.assert_allclose(evaluate_graph(r,arrays)[0],[[10.,np.nan]],equal_nan=True)
    with pytest.raises(UnsupportedEEError,match="fractional"):
        compile(call("Image.updateMask",image=im,mask=call("Image.constant",value=.5)),local)


def test_alias_dn_and_common_map(local,arrays):
    c=call("ImageCollection.load",id="COPERNICUS/S2_SR_HARMONIZED")
    r=compile(select(call("Collection.first",collection=c),"B4"),local)
    assert r["warnings"] and "pre-cloud-masked" in r["warnings"][0]
    np.testing.assert_allclose(evaluate_graph(r,arrays)[0],[[10000,30000]])
    arg={"type":"ArgumentRef","value":"im"}
    c=call("Collection.map",collection=c,baseAlgorithm={"type":"Function","argumentNames":["im"],"body":call("Image.normalizedDifference",input=arg,bandNames=["B8","B4"])})
    r=compile(call("reduce.median",collection=c),local)
    assert r["bands"]==["nd"]
    c["arguments"]["baseAlgorithm"]["body"]=call("Element.get",object=arg,property="system:time_start")
    with pytest.raises(UnsupportedEEError,match="must return an Image"): compile(c,local)


def test_static_dictionary_date_and_metadata(local):
    assert compile(call("Date.millis",date=call("Date",value="1970-01-01T00:00:01.001Z")),local)["value"]==1001
    assert compile(call("Date",value="1970"),local)["value"]==0
    assert compile(call("Date",value="1970-01"),local)["value"]==0
    assert compile(call("Number.add",left=2,right=3),local)["value"]==5
    assert compile(call("Dictionary.get",dictionary={"a":7},key="a"),local)["value"]==7
    assert compile(call("Element.get",object=first(),property="system:index"),local)["value"]=="a"
    assert compile(call("Element.get",object=call("Image.normalizedDifference",input=first(),bandNames=["nir","red"]),property="system:index"),local)["value"] is None


def test_expression_functions_broadcast_and_parameter_rejection(local,arrays):
    r=compile(expression('sqrt(pow(n.nir, 2)) + 2',n=first()),local)
    np.testing.assert_allclose(evaluate_graph(r,arrays)[0],[[3,5]])
    r=compile(expression('b("nir") > 2 ? b("nir") : 0'),local)
    np.testing.assert_allclose(evaluate_graph(r,arrays)[0],[[0,3]])
    with pytest.raises(UnsupportedEEError,match="Unknown Image.expression variable"):
        compile(expression("unknown + 1"),local)
    with pytest.raises(UnsupportedEEError,match="Unsupported algorithm arguments"):
        compile(call("Image.select",input=first(),bandSelectors=["red"],unexpected=True),local)
    # Population stdDev now computes finite lists but is never replaced by the
    # existing sample-standard-deviation raster kernel.
    assert compile(call("List.reduce",list=[0,2],reducer=call("Reducer.stdDev")),local)["value"]==1
    with pytest.raises(UnsupportedEEError,match="not a computable output"):
        compile(call("Reducer.stdDev"),local)
    with pytest.raises(UnsupportedEEError,match="static List.reduce"):
        compile(call("Image.reduce",image=first(),reducer=call("Reducer.stdDev")),local)


def test_region_and_count_contract(local,arrays):
    r=compile(call("Image.reduceRegion",image=select(first(),"red"),geometry=rect(),reducer=call("Reducer.mean")),local)
    assert r["kind"]=="region" and processes(r)[-1]=="aggregate_spatial"
    assert r["warnings"]
    count=compile(call("reduce.count",collection=call("Collection.map",collection=col(),baseAlgorithm={"type":"Function","argumentNames":["im"],"body":select({"type":"ArgumentRef","value":"im"},"nir")})),local)
    assert all("ignore_nodata" not in n["arguments"] for n in count["process_graph"].values() if n["process_id"]=="count")
    np.testing.assert_allclose(evaluate_graph(count,arrays)[0],[[3,2]])


def test_featurecollection_region_projection_wrapper(local):
    reduction=call("Image.reduceRegion",image=select(first(),"red"),geometry=rect(),reducer=call("Reducer.mean"),
                   scale=10,crs=call("Projection",crs="EPSG:32649"))
    wrapper=call("Collection",features=[call("Feature",geometry=None,metadata=reduction)])
    r=compile(wrapper,local)
    assert r["kind"]=="region" and r["bands"]==["red"]
    assert "resample_spatial" in processes(r)
    static=compile(call("Collection",features=[call("Feature",geometry=None,metadata={"mean":3.0})]),local)
    assert static["value"]=={"type":"FeatureCollection","features":[{"type":"Feature","geometry":None,"properties":{"mean":3.0}}]}


def test_map_property_copy_retains_only_requested_properties(local):
    arg={"type":"ArgumentRef","value":"im"}
    nd=call("Image.normalizedDifference",input=arg,bandNames=["nir","red"])
    body=call("Image.copyProperties",destination=nd,source=arg,properties=["system:time_start"])
    mapped=call("Collection.map",collection=col(),baseAlgorithm={"type":"Function","argumentNames":["im"],"body":body})
    r=compile(call("Collection.first",collection=mapped),local)
    assert r["properties"]=={"system:time_start":1000}
    assert r["source_item_ids"]==["a"]


def test_division_zero_and_same_length_band_naming(local,arrays):
    arrays["a"]["red"]=np.array([0.,1.])
    value=call("Image.divide",image1=select(first(),"nir"),image2=select(first(),"red"))
    r=compile(value,local)
    assert r["bands"]==["nir"]
    np.testing.assert_allclose(evaluate_graph(r,arrays)[0],[[0.,3.]])
    assert compile(call("Number.divide",left=2,right=0),local)["value"]==0


def test_unsupported_runtime_semantics_fail_explicitly(local):
    with pytest.raises(UnsupportedEEError,match="same number"):
        compile(call("Image.updateMask",image=select(first(),"nir"),mask=call("Image.gt",image1=first(),image2=0)),local)
    with pytest.raises(UnsupportedEEError,match="bestEffort"):
        compile(call("Image.reduceRegion",image=first(),geometry=rect(),reducer=call("Reducer.mean"),bestEffort=True),local)
    with pytest.raises(UnsupportedEEError,match="Versioned"):
        compile(call("ImageCollection.load",id="sentinel-2-l2a",version=1),local)
    with pytest.raises(UnsupportedEEError,match="unsupported"):
        compile(call("Projection",crs="EPSG:32649",transform=[1,0,0,0,-1,0]),local)


def test_export_region_keeps_exact_polygon_after_resampling(local):
    triangle={'type':'Polygon','coordinates':[[[0,0],[2,0],[0,2],[0,0]]]}
    result=compile_expression(select(first(),'red'),*local,options={'region':triangle,'scale':10,'crs':'EPSG:32649'})
    graph=result['process_graph']
    output=next(node for node in graph.values() if node.get('result'))
    assert output['process_id']=='mask_polygon'
    assert output['arguments']['mask']==triangle
    assert graph[output['arguments']['data']['from_node']]['process_id']=='resample_spatial'


SDK = json.loads((Path(__file__).parent/'fixtures/ee-sdk-1.7.49.json').read_text())['expressions']


@pytest.mark.parametrize(('name','expected'), [
    ('dates', ['2024-01-31','2024-02-29','2024-03-31']),
    ('dateYear', '2025-02-28T12:34:56.789+00:00'),
    ('dateUnits', [2024,2,29,12,34,56]), ('iterate', 10), ('dropNulls',[2,3]),
    ('listHelpers',[2,3]), ('listKeys',['b','a','c']), ('properties',['c','b','a']),
    ('toList',[1001,2000]), ('inList',['a','c']), ('calendar',3),
    ('staticMapMetadata',['accepted']*3), ('copiedMapDate',2),
    ('fromImagesMetadata',[1970]*3),('fromImagesSize',3),('fromImagesEmptySize',0),('fromImagesPeriodDates',[1000,1001]),
])
def test_official_sdk_static_contracts(local, name, expected):
    assert compile(SDK[name], local)['value'] == expected


def test_official_sdk_where_mask_fallback(local, arrays):
    arrays['a']={k: np.ones(5) for k in arrays['a']}
    arrays['a']['nir']=np.array([1.,2.,np.nan,4.,5.])
    arrays['a']['green']=np.array([1.,np.nan,1.,0.,1.])
    arrays['a']['blue']=np.array([9.,9.,9.,9.,np.nan])
    # Masked test/value falls back to input; masked input is never resurrected.
    result=compile(SDK['whereMasked'], local)
    np.testing.assert_allclose(evaluate_graph(result, arrays)[0], [[9.,2.,np.nan,4.,5.]], equal_nan=True)


def test_official_sdk_image_helpers(local, arrays):
    arrays['a']['nir']=np.array([-1.,9.]); arrays['a']['red']=np.array([3.,1.])
    np.testing.assert_allclose(evaluate_graph(compile(SDK['clamp'], local),arrays)[0], [[2.,6.]])
    np.testing.assert_allclose(evaluate_graph(compile(SDK['unitScale'], local),arrays)[0], [[-.5,2.]])
    np.testing.assert_allclose(evaluate_graph(compile(SDK['reduceBands'], local),arrays)[0], [[1.,5.]])
    assert compile(SDK['reduceCollection'], local)['bands']==['nir_mean']
    assert compile(SDK['toBands'], local)['bands']==['a_nir','b_nir']
    assert compile(SDK['selectRename'], local)['bands']==['N','R','N_1']
    np.testing.assert_allclose(evaluate_graph(compile(SDK['whereConstant'], local),arrays)[0],[[0.,9.]])
    np.testing.assert_allclose(evaluate_graph(compile(SDK['constantMath'], local),arrays)[0],[[-2.,18.]])


def test_official_sdk_footprint_and_expected_rejections(local):
    from shapely.geometry import shape
    assert shape(compile(SDK['imageGeometry'],local)['value']).area == 4
    assert shape(compile(SDK['collectionGeometry'],local)['value']).area == 10
    with pytest.raises(UnsupportedEEError,match='did not match'): compile(SDK['missingBand'], local)
    with pytest.raises(UnsupportedEEError,match='token'): compile(SDK['invalidPattern'], local)
    with pytest.raises(UnsupportedEEError,match='integer'):
        compile(call('Date.advance',date=0,delta=.5,unit='month'), local)


def test_static_map_metadata_controls_filter_and_sort(local):
    arg={'type':'ArgumentRef','value':'im'}
    changed=call('Collection.map',collection=col(),baseAlgorithm={'type':'Function','argumentNames':['im'],
        'body':call('Element.set',object=arg,key='system:time_start',value=3000)})
    filt=call('Filter.dateRangeContains',rightField='system:time_start',leftValue=call('DateRange',start=1000,end=2001))
    assert compile(call('Collection.size',collection=call('Collection.filter',collection=changed,filter=filt)),local)['value']==0
    lost=call('Collection.map',collection=col(),baseAlgorithm={'type':'Function','argumentNames':['im'],
        'body':call('Image.normalizedDifference',input=arg,bandNames=['nir','red'])})
    with pytest.raises(UnsupportedEEError,match='unavailable'):
        compile(call('Collection.filter',collection=lost,filter=filt),local)


def test_mapped_clip_controls_footprint_selection(local):
    arg={'type':'ArgumentRef','value':'im'}
    clipped=call('Collection.map',collection=col(),baseAlgorithm={'type':'Function','argumentNames':['im'],
        'body':call('Image.clip',input=arg,geometry=rect(0,0,.5,.5))})
    filt=call('Filter.intersects',leftField='.all',rightValue=call('Feature',geometry=rect(1,1,1.5,1.5)))
    assert compile(call('Collection.size',collection=call('Collection.filter',collection=clipped,filter=filt)),local)['value']==0
    from shapely.geometry import shape
    for value in [clipped,call('reduce.median',collection=clipped)]:
        algorithm='Collection.geometry' if value is clipped else 'Image.geometry'
        assert shape(compile(call(algorithm,**{'collection' if value is clipped else 'feature':value}),local)['value']).area==.25


def test_if_is_lazy_and_computed_lists_are_bounded(local):
    assert compile(call('If',condition=True,trueCase=3,falseCase=call('NotImplemented')),local)['value']==3
    argument={'type':'ArgumentRef','value':'a'}
    grow=call('List.iterate',list=list(range(20)),first=[0],function={'type':'Function','argumentNames':['x','a'],
        'body':call('List.cat',list1=argument,list2=argument)})
    with pytest.raises(UnsupportedEEError,match='10000'): compile(grow,local)


@pytest.mark.parametrize(('name','expected'),[
    ('fromImagesMean',[[5.,3.]]),('fromImagesPeriods',[[5.,3.]]),
    ('mergedMean',[[5.,3.]]),('fromImagesDuplicateSum',[[2.,6.]]),
    ('fromImagesDuplicateCount',[[2.,2.]]),('fromImagesSortedMosaic',[[9.,3.]]),
])
def test_official_sdk_constructed_image_sequences(local,arrays,name,expected):
    np.testing.assert_allclose(evaluate_graph(compile(SDK[name],local),arrays)[0],expected,equal_nan=True)


def test_constructed_sequence_geometry_and_failures(local):
    from shapely.geometry import shape
    sequence=call('ImageCollection.fromImages',images=call('Collection.toList',collection=col(),count=3))
    composite=call('reduce.mean',collection=sequence)
    assert shape(compile(call('Image.geometry',feature=composite),local)['value']).area==10
    metadata=compile(sequence,local)
    assert metadata['features'][1]['properties']['system:index']=='b'
    assert metadata['has_time_dimension'] is True
    with pytest.raises(UnsupportedEEError,match='empty'):
        compile(call('Collection.first',collection=call('ImageCollection.fromImages',images=[])),local)
    with pytest.raises(UnsupportedEEError,match='at most 1000'):
        compile(call('ImageCollection.fromImages',images=[1]*1001),local)
