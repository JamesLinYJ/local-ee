"""Canonical graph assembly, source snapshots and output grid limits."""
import json
import math
import re

from .ir import Pixel, fail
from .pixel_graph import PixelCompiler


class Graph(PixelCompiler):
    def __init__(self, translator):
        self.t = translator
        self.graph = {}
        self.cache = {}
        self.sources = {}
        self.required_bands = {}
        self.expressions = {}
        self.double_precision = {}

    def node(self, process_id, **args):
        key = json.dumps([process_id, args], sort_keys=True)
        if key not in self.cache:
            if len(self.graph) >= 500: fail("Compiled process graph exceeds 500 nodes; reduce the script scope")
            nid = "n"+str(len(self.graph))
            self.graph[nid] = {"process_id": process_id, "arguments": args}
            self.cache[key] = {"from_node": nid}
        return self.cache[key]

    def callback(self, process, args):
        return {"process_graph": {"p": {"process_id": process, "arguments": args, "result": True}}}

    def source(self, source):
        if source not in self.sources:
            if not source.ids: fail("Collection filter has no locally available images")
            extent = self.t.options.get("region")
            if extent:
                from shapely.geometry import shape
                w, s, e, n = shape(extent).bounds
            else:
                bounds = [self.t.member(source, i).get("bbox") for i in source.ids]
                if any(b is None for b in bounds): fail("Local items need bbox metadata")
                w, s, e, n = min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds)
            self.sources[source] = self.node("load_collection", id=source.cid,
                spatial_extent={"west": w, "south": s, "east": e, "north": n},
                _gee_item_ids=list(source.ids), bands=[n for n in source.names if n in self.required_bands.get(source, source.names)])
        return self.sources[source]

    def image(self, image):
        seen = set()
        def collect(value):
            if isinstance(value, Pixel):
                if id(value) in seen: return
                seen.add(id(value))
                if value.op == "band": self.required_bands.setdefault(value.args[0], set()).add(value.args[1])
                else:
                    for operand in value.args: collect(operand)
            elif isinstance(value, tuple):
                for operand in value: collect(operand)
        for _, pixel in image.bands: collect(pixel)
        out = None; time_state = None
        for name, pixel in image.bands:
            ref, label, timed = self.expression(pixel)
            if label is None:
                fail("A standalone constant image needs a raster grid and unmasked constant raster support")
            if time_state is not None and timed != time_state: fail("Image bands have incompatible time dimensions")
            time_state = timed
            ref = self.node("rename_labels", data=ref, dimension="bands", target=[name])
            out = ref if out is None else self.node("merge_cubes", cube1=out, cube2=ref)
        scale = self.t.options.get("scale")
        crs = self.t.options.get("crs")
        if scale is not None or crs is not None:
            if scale is None or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0: fail("A positive scale in meters is required when setting output scale/CRS")
            if crs is not None and not re.fullmatch(r"EPSG:\d+", crs): fail("CRS must be an EPSG code")
            if crs == "EPSG:4326": fail("Meter-scale output in geographic EPSG:4326 needs projection-aware grid support")
            out = self.node("resample_spatial", data=out, resolution=scale, method="near", **({"projection": int(crs[5:])} if crs else {}))
        if self.t.options.get("region") is not None:
            # A nonrectangular export region must mask pixels, not merely limit
            # the source query to the region's bounding box.
            out = self.node("mask_polygon", data=out, mask=self.t.options["region"])
        return out, time_state

    def finish(self, ref):
        self.graph[ref["from_node"]]["result"] = True
        if len(self.graph) > 500: fail("Compiled process graph exceeds 500 nodes; reduce the script scope")
        return self.graph
