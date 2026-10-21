"""Conservative preflight, independent of GEE's requested maxPixels ceiling."""
import math

from ..ee_translate import UnsupportedEEError


def pixel_budget(compiled, items, options, max_pixels):
    from rasterio.crs import CRS
    from rasterio.warp import transform_bounds
    if isinstance(max_pixels,bool) or not isinstance(max_pixels,(int,float)) or not math.isfinite(max_pixels) or max_pixels < 1 or int(max_pixels)!=max_pixels:
        raise ValueError('maxPixels must be a positive finite integer')
    loads=[node['arguments'] for node in compiled['process_graph'].values() if node['process_id']=='load_collection']
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
