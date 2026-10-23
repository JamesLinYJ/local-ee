"""Terrain from a locally synchronized, versioned Copernicus DEM collection.

No download occurs here. Only normalized ``cop-dem-glo-30/v1`` items are
accepted; legacy items require a controlled resynchronization. This local
collection has one ``elevation`` band in metres, not Google's full DEM asset.
Choose a study area that intersects an already ingested tile. ``first`` selects
one real tile; it does not mosaic a region or fill missing neighboring tiles.
"""


def build_workflow(ee, region):
    collection = ee.ImageCollection("cop-dem-glo-30").filterBounds(region)
    elevation = collection.first().select("elevation")
    products = ee.Terrain.products(elevation)
    return {
        "elevation": elevation,
        "slope": ee.Terrain.slope(elevation),
        "aspect": ee.Terrain.aspect(elevation),
        "hillshade": ee.Terrain.hillshade(elevation),
        "products": products,
        "clipped_products": products.clip(region),
    }


def build_export_task(ee, image, region, *, output_crs, output_scale):
    """Prepare a local export with an explicit metre-based projected CRS.

    Output reprojection happens after terrain uses the original source grid.
    The local toDrive adapter creates a workbench result, not a Google upload.
    Review the task, then call start() explicitly in the workbench.
    """
    return ee.batch.Export.image.toDrive(
        image=image,
        description="local_dem_terrain",
        fileNamePrefix="local_dem_terrain",
        region=region,
        crs=output_crs,
        scale=output_scale,
        maxPixels=1_000_000,
        fileFormat="GeoTIFF",
    )
