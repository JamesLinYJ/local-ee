"""Fixed SDK-authored calls and versioned synthetic metadata for Python probes."""
from __future__ import annotations

from typing import Any

COLLECTION_ID = "sentinel-2-l2a"
BANDS = ["blue", "green", "red", "nir", "SCL"]
ROI = "ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9], proj='EPSG:4326', geodesic=False)"


# These are valid calls against signatures generated from the pinned upstream
# algorithms.json. A compile rejection therefore identifies local semantics,
# rather than an intentionally malformed signature argument.
CASES = [
    ("number_add", "values", "ee.Number(4).add(right=5)"),
    ("number_divide_format", "values", "ee.Number(7).divide(right=2).format(pattern='%.2f')"),
    ("date_get_year", "dates", "ee.Date('2023-11-14').get(unit='year')"),
    ("date_difference_days", "dates", "ee.Date('2023-11-15').difference(start=ee.Date('2023-11-14'), unit='day')"),
    ("date_advance", "dates", "ee.Date('2023-11-14').advance(delta=2, unit='day').format()"),
    ("list_map_lambda", "lists", "ee.List([1, 2, 3]).map(lambda item: ee.Number(item).multiply(right=2))"),
    ("list_iterate_lambda", "lists", "ee.List([1, 2, 3]).iterate(lambda item, acc: ee.Number(acc).add(right=item), first=ee.Number(0))"),
    ("dictionary_get", "dictionaries", "ee.Dictionary({'mean': 4, 'count': 2}).get(key='mean')"),
    ("conditional", "values", "ee.Algorithms.If(condition=ee.Number(2).gt(right=1), trueCase='yes', falseCase='no')"),
    ("geometry_rectangle", "geometry", ROI),
    ("collection_load", "collections", f"ee.ImageCollection('{COLLECTION_ID}')"),
    ("filter_date", "collections", f"ee.ImageCollection('{COLLECTION_ID}').filterDate(start='2023-11-14', end='2023-11-16')"),
    ("filter_bounds", "collections", f"ee.ImageCollection('{COLLECTION_ID}').filterBounds(geometry=roi)"),
    ("filter_metadata", "filters", f"ee.ImageCollection('{COLLECTION_ID}').filter(ee.Filter.lte(name='cloud', value=10))"),
    ("filter_and_sort", "filters", f"ee.ImageCollection('{COLLECTION_ID}').filter(ee.Filter.And(ee.Filter.lte('cloud', 20), ee.Filter.gte('system:time_start', 1700000000000))).sort(prop='cloud', ascending=False)"),
    ("select_named_bands", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().select(selectors=['nir', 'red'], names=['NIR', 'RED'])"),
    ("map_ndvi_copy_properties", "mapped_collections", f"ee.ImageCollection('{COLLECTION_ID}').map(lambda image: image.normalizedDifference(bandNames=['nir', 'red']).rename(names=['NDVI']).copyProperties(source=image, properties=['system:time_start']))"),
    ("expression_ndvi", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().expression(expression='(nir - red) / (nir + red)', map_={{'nir': ee.ImageCollection('{COLLECTION_ID}').first().select('nir'), 'red': ee.ImageCollection('{COLLECTION_ID}').first().select('red')}}).rename('NDVI')"),
    ("addbands_constant_named", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().select('red').addBands(srcImg=ee.Image.constant(value=4).rename('constant'), names=['constant'], overwrite=False)"),
    ("update_mask", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().updateMask(mask=ee.ImageCollection('{COLLECTION_ID}').first().select('SCL').neq(image2=9))"),
    ("unmask_fill", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().select('nir').unmask(value=-9999, sameFootprint=False)"),
    ("where_threshold", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().select('nir').where(test=ee.ImageCollection('{COLLECTION_ID}').first().select('nir').lt(image2=2), value=0)"),
    ("clip_region", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().clip(clip_geometry=roi)"),
    ("reduce_region_named", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').first().reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=10, maxPixels=1000)"),
    ("collection_mean", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').mean()"),
    ("collection_median", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').median()"),
    ("collection_max", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').max()"),
    ("collection_mosaic", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').mosaic()"),
    ("quality_mosaic", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').qualityMosaic(qualityBand='nir')"),
    ("collection_count", "reductions", f"ee.ImageCollection('{COLLECTION_ID}').count()"),
    ("collection_to_bands", "collections", f"ee.ImageCollection('{COLLECTION_ID}').select('nir').toBands()"),
    ("collection_from_images", "collections", f"ee.ImageCollection.fromImages(images=[ee.ImageCollection('{COLLECTION_ID}').first(), ee.ImageCollection('{COLLECTION_ID}').first()])"),
    ("collection_limit_sort", "collections", f"ee.ImageCollection('{COLLECTION_ID}').limit(maximum=2, prop='cloud', ascending=True)"),
    ("map_copy_system_properties", "mapped_collections", f"ee.ImageCollection('{COLLECTION_ID}').map(lambda image: image.copyProperties(source=image, properties=['system:index', 'system:time_start']))"),
    ("map_set_dynamic_property", "mapped_collections", f"ee.ImageCollection('{COLLECTION_ID}').map(lambda image: image.set('is_clear', ee.Number(image.get('cloud')).lte(right=10)))"),
    ("map_arithmetic_rename", "mapped_collections", f"ee.ImageCollection('{COLLECTION_ID}').map(lambda image: image.select('nir').multiply(image2=0.0001).rename('reflectance'))"),
    ("first_dynamic_property", "properties", f"ee.ImageCollection('{COLLECTION_ID}').first().get(property='system:index')"),
    ("aggregate_array_properties", "properties", f"ee.ImageCollection('{COLLECTION_ID}').aggregate_array(property='system:index')"),
    ("filter_date_algorithm", "filters", f"ee.ImageCollection('{COLLECTION_ID}').filter(ee.Filter.date(start='2023-11-14', end='2023-11-16'))"),
    ("map_expression", "mapped_collections", f"ee.ImageCollection('{COLLECTION_ID}').map(lambda image: image.expression(expression='nir - red', map_={{'nir': image.select('nir'), 'red': image.select('red')}}).rename('difference'))"),
    ("image_band_names", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().bandNames()"),
    ("image_to_float", "images", f"ee.ImageCollection('{COLLECTION_ID}').first().select('nir').toFloat()"),
    ("neighborhood_reduce_kernel", "neighborhood", f"ee.ImageCollection('{COLLECTION_ID}').first().reduceNeighborhood(reducer=ee.Reducer.mean(), kernel=ee.Kernel.square(radius=1, units='pixels', normalize=False))"),
    ("focal_mean", "neighborhood", f"ee.ImageCollection('{COLLECTION_ID}').first().focalMean(radius=1, kernelType='circle', units='pixels', iterations=1)"),
    ("join_save_first", "joins", f"ee.Join.saveFirst(matchKey='match').apply(primary=ee.ImageCollection('{COLLECTION_ID}'), secondary=ee.ImageCollection('{COLLECTION_ID}'), condition=ee.Filter.equals(leftField='system:index', rightField='system:index'))"),
    ("array_matrix_multiply", "arrays", "ee.Array([[1, 2], [3, 4]]).matrixMultiply(right=ee.Array([[1], [1]]))"),
    ("regression_reducer", "regression", "ee.ImageCollection('sentinel-2-l2a').reduce(reducer=ee.Reducer.linearRegression(numX=2, numY=1))"),
    ("classifier_constructor", "classifiers", "ee.Classifier.smileRandomForest(numberOfTrees=10, variablesPerSplit=2, minLeafPopulation=1, bagFraction=0.5, seed=7)"),
    ("export_image_drive", "exports", f"ee.batch.Export.image.toDrive(image=ee.ImageCollection('{COLLECTION_ID}').first().select('nir').rename('NIR'), description='python-probe-image', folder='research', fileNamePrefix='nir', region=roi, scale=10, crs='EPSG:32649', maxPixels=1000)"),
    ("export_table_drive", "exports", f"ee.batch.Export.table.toDrive(collection=ee.FeatureCollection([ee.Feature(roi, {{'mean': 3, 'scene': 'a'}})]), description='python-probe-table', folder='research', fileNamePrefix='summary', fileFormat='CSV', selectors=['mean', 'scene'])"),
]


def synthetic_inputs() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Metadata-only synthetic local catalogue; no raster files are read."""
    items = []
    for scene, millis, cloud in (
        ("scene-a", 1_700_000_000_000, 10),
        ("scene-b", 1_700_086_400_000, 20),
        ("scene-c", 1_700_172_800_000, 5),
    ):
        items.append({
            "id": scene,
            "type": "Feature",
            "bbox": [100, 30, 101, 31],
            "geometry": {"type": "Polygon", "coordinates": [[[100, 30], [101, 30], [101, 31], [100, 31], [100, 30]]]},
            "properties": {
                "datetime": "2023-11-14T22:13:20Z",
                "system:time_start": millis,
                "system:index": scene,
                "cloud": cloud,
            },
        })
    metadata = {
        "id": COLLECTION_ID,
        "type": "Collection",
        "bbox": [100, 30, 101, 31],
        "extent": {
            "spatial": {"bbox": [[100, 30, 101, 31]]},
            "temporal": {"interval": [["2023-11-14T00:00:00Z", "2023-11-17T00:00:00Z"]]},
        },
        "summaries": {"eo:bands": [{"name": band} for band in BANDS]},
        "cube:dimensions": {"bands": {"values": BANDS}},
    }
    roi = {"type": "Polygon", "coordinates": [[[100.1, 30.1], [100.9, 30.1], [100.9, 30.9], [100.1, 30.9], [100.1, 30.1]]]}
    return metadata, {COLLECTION_ID: items}, roi
