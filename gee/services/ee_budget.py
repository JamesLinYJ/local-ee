"""Conservative preflight, independent of GEE's requested maxPixels ceiling."""
import math

from ..ee_translate import UnsupportedEEError


def _output_raster_loads(compiled):
    """Follow output raster edges; a trained model does not expand its grid.

    Sampling/training work is checked separately by ``sample_input_budget``.
    Callback graphs have their own scope and cannot declare top-level loads.
    """
    process = compiled['process_graph']
    results = [key for key, node in process.items() if node.get('result') is True]
    if len(results) != 1:
        raise ValueError('Pixel preflight requires one raster result node')
    pending, seen, loads = list(results), set(), []

    def references(value):
        if isinstance(value, dict):
            if set(value) == {'from_node'}:
                yield value['from_node']
            elif 'process_graph' not in value:
                for child in value.values():
                    yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        node = process[key]
        if node['process_id'] == 'load_collection':
            loads.append(node['arguments'])
        arguments = node.get('arguments', {})
        if node['process_id'] == 'local_ee_minimum_distance':
            arguments = {'data': arguments['data']}
        pending.extend(references(arguments))
    return loads


def pixel_budget(compiled, items, options, max_pixels):
    from rasterio.crs import CRS
    from rasterio.warp import transform_bounds
    if isinstance(max_pixels,bool) or not isinstance(max_pixels,(int,float)) or not math.isfinite(max_pixels) or max_pixels < 1 or int(max_pixels)!=max_pixels:
        raise ValueError('maxPixels must be a positive finite integer')
    loads=_output_raster_loads(compiled)
    native=[]; extents=[]
    for args in loads:
        by_id={item['id']:item for item in items[args['id']]}
        for iid in args['_gee_item_ids']:
            item=by_id[iid]
            for name in args['bands']:
                asset=item.get('assets',{}).get(name,{})
                transform=asset.get('proj:transform'); epsg=asset.get('proj:epsg',item.get('properties',{}).get('proj:epsg'))
                if transform and len(transform)>=6 and epsg and transform[1]==0 and transform[3]==0:
                    native.append((epsg,abs(transform[0]),abs(transform[4])))
        bbox=args['spatial_extent']; extents.append((bbox['west'],bbox['south'],bbox['east'],bbox['north']))
    if not native:raise UnsupportedEEError('maxPixels preflight requires local projection/transform metadata')
    projection=CRS.from_user_input(options.get('crs') or native[0][0])
    if not projection.is_projected or projection.linear_units_factor[1]!=1:
        raise UnsupportedEEError('Pixel budget currently requires a projected CRS in meters')
    scale=options.get('scale')
    if scale is not None:
        if isinstance(scale,bool) or not isinstance(scale,(int,float)) or not math.isfinite(scale) or scale<=0:raise ValueError('scale must be positive and finite')
        xres=yres=scale
    else:
        if len(set(native))!=1 or projection!=CRS.from_epsg(native[0][0]):raise UnsupportedEEError('Mixed local grids require explicit scale and crs')
        _,xres,yres=native[0]
    geometry=compiled.get('geometry') or options.get('region')
    if geometry:
        from shapely.geometry import shape
        extent=shape(geometry).bounds
    else:extent=(min(x[0] for x in extents),min(x[1] for x in extents),max(x[2] for x in extents),max(x[3] for x in extents))
    left,bottom,right,top=transform_bounds(4326,projection,*extent,densify_pts=21)
    # Four extra cells cover pixel-grid alignment and projection-bound padding.
    upper=(math.ceil((right-left)/xres)+4)*(math.ceil((top-bottom)/yres)+4)
    if not math.isfinite(upper) or upper < 1:raise ValueError('Invalid projected output extent')
    server_limit=100_000_000
    if upper > min(max_pixels,server_limit):
        raise ValueError(f'Conservative pixel bound {upper} exceeds maxPixels/local limit {min(max_pixels,server_limit):g}; reduce region or use a coarser scale')
    return {'conservative_pixels_per_band':upper,'requested_max_pixels':max_pixels,'local_limit':server_limit,'crs':str(projection),'resolution':[xres,yres]}


def sample_input_budget(compiled, items):
    """Bound input asset-grid cells for every sample branch, including training.

    This works in native pixel coordinates for geographic or projected grids;
    it does not reinterpret degrees as meters. Native tile/key/decoded budgets
    remain mandatory because padded tiles and actual execution differ from an
    asset-grid estimate. No raster values are read during this preflight.
    """
    from rasterio.warp import transform_bounds

    process = compiled['process_graph']
    samples = [node for node in process.values() if node['process_id'] == 'local_ee_sample_regions']
    if not samples:
        return None
    loads, visited = {}, set()

    def references(value):
        if isinstance(value, dict):
            if set(value) == {'from_node'}:
                yield value['from_node']
            else:
                for child in value.values():
                    yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    def visit(key):
        if key in visited:
            return
        visited.add(key)
        node = process[key]
        if node['process_id'] == 'load_collection':
            loads[key] = node['arguments']
        for child in references(node.get('arguments', {})):
            visit(child)

    for node in samples:
        visit(node['arguments']['data']['from_node'])
    total = 0
    for args in loads.values():
        by_id = {item['id']: item for item in items[args['id']]}
        bbox = args['spatial_extent']
        for item_id in args['_gee_item_ids']:
            item = by_id[item_id]
            for band in args['bands']:
                asset = item.get('assets', {}).get(band, {})
                shape = asset.get('proj:shape')
                transform = asset.get('proj:transform')
                epsg = asset.get('proj:epsg', item.get('properties', {}).get('proj:epsg'))
                if (not isinstance(shape, list) or len(shape) != 2
                        or any(type(x) is not int or x <= 0 for x in shape)
                        or not isinstance(transform, list) or len(transform) < 6
                        or any(type(x) not in (int, float) or not math.isfinite(x) for x in transform[:6])
                        or transform[1] != 0 or transform[3] != 0
                        or transform[0] <= 0 or transform[4] >= 0 or not epsg):
                    raise UnsupportedEEError('Sample preflight requires finite axis-aligned local asset shape/transform/CRS metadata')
                left, bottom, right, top = transform_bounds(
                    4326, epsg, bbox['west'], bbox['south'], bbox['east'], bbox['north'], densify_pts=21)
                if not all(math.isfinite(x) for x in (left, bottom, right, top)):
                    raise ValueError('Invalid sampling source projection extent')
                width = min(shape[1], math.ceil(max(0, right - left) / transform[0]) + 4)
                height = min(shape[0], math.ceil(max(0, top - bottom) / -transform[4]) + 4)
                total += width * height
                if total > 100_000_000:
                    raise ValueError('Sample input exceeds the 100000000 asset-grid cell preflight limit')
    if not loads:
        raise UnsupportedEEError('Sampling requires a bounded local raster source')
    return {'input_asset_grid_cells': total, 'local_limit': 100_000_000,
            'runtime_tile_grid_key_work_limits': 'separately enforced by native sampler'}
