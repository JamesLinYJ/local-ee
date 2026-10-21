"""Small explicit supported process surface; no URLs, UDFs or remote namespaces."""
import copy
import hashlib
import json
from pathlib import Path
from .local_processes import LOCAL_PROCESSES, validate_local_process

SUPPORTED = {
    "load_collection", "filter_bbox", "filter_temporal", "filter_bands", "mask",
    "ndvi", "normalized_difference", "reduce_dimension",
    "aggregate_temporal_period", "aggregate_spatial", "resample_spatial",
    "apply", "apply_dimension", "array_element", "array_create", "add", "subtract",
    "multiply", "divide", "mean", "median", "min", "max", "sum", "count", "sd",
    "eq", "neq", "gt", "gte", "lt", "lte", "or", "and", "not", "is_nodata",
    "if", "save_result", "rename_labels", "merge_cubes", "mask_polygon",
    "add_dimension", "drop_dimension", "first", "last", "absolute", "power",
    "sqrt", "log", "exp", "round", "floor", "ceil", "mod", "cos", "sin", "tan",
    *LOCAL_PROCESSES,
}

def validate(graph):
    if not isinstance(graph, dict) or not graph or len(json.dumps(graph)) > 1000000:
        raise ValueError("需要非空 openEO process_graph（最大 1 MB）")
    def walk(g, depth=0):
        if depth > 32:
            raise ValueError("流程嵌套超过 32 层")
        if not isinstance(g, dict) or not g:
            raise ValueError("子流程不能为空")
        if len(g) > 500:
            raise ValueError("单个流程最多 500 个节点")
        if sum(n.get("result") is True for n in g.values() if isinstance(n, dict)) != 1:
            raise ValueError("每个流程必须有一个 result 节点")
        deps = {}
        for key, node in g.items():
            if not isinstance(node, dict) or set(node) - {"process_id", "arguments", "result", "description", "namespace"} or node.get("process_id") not in SUPPORTED or node.get("namespace"):
                raise ValueError("不支持的算子或远程 namespace")
            if "description" in node and not isinstance(node["description"],str):
                raise ValueError("description 必须是字符串")
            if "result" in node and not isinstance(node["result"],bool):
                raise ValueError("result 必须是布尔值")
            args = node.get("arguments", {})
            if not isinstance(args, dict):
                raise ValueError("arguments 必须是对象")
            deps[key] = set()
            def visit(value, level=depth):
                if level > 64: raise ValueError("参数嵌套过深")
                if isinstance(value, dict):
                    if any(k in value for k in ("process_id", "node", "callback", "namespace", "result_cache")):
                        raise ValueError("参数必须使用规范引用或 process_graph，不接受内嵌可执行节点")
                    if "process_graph" in value:
                        if set(value) != {"process_graph"}:
                            raise ValueError("process_graph 不能与其他参数表示混用")
                        walk(value["process_graph"], level+1)
                        return
                    if "from_node" in value:
                        if set(value) != {"from_node"}:
                            raise ValueError("from_node 不能与其他参数表示混用")
                        if not isinstance(value["from_node"], str) or value["from_node"] not in g:
                            raise ValueError("引用不存在的节点")
                        deps[key].add(value["from_node"])
                    if "from_parameter" in value and (set(value) != {"from_parameter"} or not isinstance(value["from_parameter"], str)):
                        raise ValueError("from_parameter 必须是独立的字符串引用")
                    for v in value.values(): visit(v,level+1)
                elif isinstance(value, list):
                    for v in value: visit(v,level+1)
            visit(args)
            if node["process_id"] == "load_collection" and "_gee_item_ids" in args:
                ids=args["_gee_item_ids"]
                if not isinstance(ids,list) or not ids or len(ids)>1000 or any(not isinstance(x,str) or not x or len(x)>256 for x in ids) or len(set(ids))!=len(ids):
                    raise ValueError("GEE item selection must contain 1..1000 unique item IDs")
            if node["process_id"] in LOCAL_PROCESSES:
                validate_local_process(node["process_id"], args, depth)
            if node["process_id"] == "mask_polygon" and not isinstance(args.get("mask"),dict):
                raise ValueError("多边形掩膜需要内嵌 GeoJSON，不接受 URL 或文件路径")
            if node["process_id"] == "load_collection" and args.get("properties"):
                raise ValueError("当前不支持属性过滤；请使用波段、日期和范围过滤")
            if node["process_id"] == "aggregate_spatial" and isinstance(args.get("geometries"),str):
                raise ValueError("区域统计需要内嵌 GeoJSON，不接受 URL 或文件路径")
            if node["process_id"] == "save_result":
                if args.get("format", "").lower() not in {"gtiff", "geotiff", "netcdf", "csv"}:
                    raise ValueError("仅支持 GeoTIFF、NetCDF、CSV")
                if args.get("options"):
                    raise ValueError("首版不接受自定义 save_result options")
        done, active = set(), set()
        def check(k):
            if k in active: raise ValueError("流程有循环依赖")
            if k in done: return
            active.add(k)
            for d in deps[k]: check(d)
            active.remove(k); done.add(k)
        for k in deps: check(k)
    walk(graph)

def materialize(graph, collections, output):
    """Freeze the local catalog at submission; workers never resolve external URLs."""
    validate(graph)
    g = copy.deepcopy(graph)
    def visit(value):
        if isinstance(value, dict):
            if value.get("process_id") == "load_collection":
                args = value["arguments"]
                collection = args.pop("id")
                if collection not in collections:
                    raise ValueError(f"没有已入库的数据集: {collection}")
                args.pop("properties", None)  # Empty only; nonempty filters are rejected above.
                selection=args.pop("_gee_item_ids",None)
                args["url"] = str(Path(output)/f"catalog-{catalog_key(collection,selection)}.json")
                value["process_id"] = "load_stac"
            for v in value.values(): visit(v)
        elif isinstance(value, list):
            for v in value: visit(v)
    visit(g)
    return g


def catalog_key(collection, item_ids=None):
    if item_ids is None:
        return collection
    digest=hashlib.sha256(json.dumps([collection,item_ids],separators=(',',':')).encode()).hexdigest()[:20]
    return "gee-"+digest


def collection_loads(process_graph):
    """Only canonical validated nodes can declare a trusted snapshot selection."""
    validate(process_graph)
    result={}
    def visit(value):
        if isinstance(value,dict):
            if value.get('process_id')=='load_collection':
                args=value['arguments'];cid=args['id'];selection=args.get('_gee_item_ids')
                result[catalog_key(cid,selection)]=(cid,selection)
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(process_graph)
    return result
