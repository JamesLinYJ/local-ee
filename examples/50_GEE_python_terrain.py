"""Terrain derivatives on a locally catalogued synthetic DEM collection.

The collection must declare the ``elevation`` and ``quality`` bands and one
common CRS/affine transform for at least two scenes. This example builds lazy
official-client expressions only; it does not download a DEM or run pixels.
The production EE DEM catalog adapter is pending; tests inject synthetic
elevation metadata under the existing accepted fixture ID, not live imagery.
"""


ROI = [100.2, 30.2, 100.8, 30.8]


def build_workflow(ee, collection):
    scene = collection.first()
    multiband = scene.select(["elevation", "quality"]).set(
        "workflow", "synthetic-terrain"
    )
    elevation = multiband.select("elevation")
    roi = ee.Geometry.Rectangle(ROI, "EPSG:4326", False)
    offset_kernel = ee.Kernel.fixed(
        width=3, height=3,
        weights=[[0, -2, 0], [0, 0, 0], [3, 0, 0]],
        x=1, y=1, normalize=False,
    )
    smooth = elevation.focalMean(radius=1, units="pixels", kernelType="square")
    convolved = smooth.convolve(ee.Kernel.gaussian(radius=1, sigma=1))
    slope = ee.Terrain.slope(elevation)
    neighborhood_slope = slope.neighborhoodToBands(offset_kernel)
    context_reducer = ee.Reducer.mean().combine(
        reducer2=ee.Reducer.stdDev(), sharedInputs=True,
    )
    products = ee.Terrain.products(elevation)
    masked = multiband.updateMask(multiband.select("quality").gt(0))

    return {
        "slope_default": slope,
        "aspect_default": ee.Terrain.aspect(elevation),
        "hillshade_default": ee.Terrain.hillshade(elevation),
        "hillshade_explicit_defaults": ee.Terrain.hillshade(
            elevation, azimuth=None, elevation=None,
        ),
        "hillshade_periodic_angles": ee.Terrain.hillshade(
            elevation, azimuth=630, elevation=-300,
        ),
        "products_single_band": products,
        "products_multiband": ee.Terrain.products(multiband),
        "new_products_only": products.select(["slope", "aspect", "hillshade"]),
        "products_multiband_masked": ee.Terrain.products(masked),
        "hillshade_smoothed_convolved": ee.Terrain.hillshade(convolved),
        "slope_observations": collection.map(
            lambda image: ee.Terrain.slope(image.select("elevation"))
        ),
        "mean_slope": collection.map(
            lambda image: ee.Terrain.slope(image.select("elevation"))
        ).mean(),
        "clip_before_products": ee.Terrain.products(elevation.clip(roi)),
        "products_clip_after": products.clip(roi),
        "source_neighborhood_bands": elevation.neighborhoodToBands(offset_kernel),
        "slope_neighborhood_bands": neighborhood_slope,
        "terrain_context_statistics": slope.addBands(neighborhood_slope)
        .reduceNeighborhood(context_reducer, ee.Kernel.square(radius=1)),
        "deprecated_products_alias": ee.Algorithms.Terrain(elevation),
    }


def build_export_task(ee, image):
    """Prepare a local GeoTIFF export over the same explicit study ROI."""
    roi = ee.Geometry.Rectangle(ROI, "EPSG:4326", False)
    return ee.batch.Export.image.toDrive(
        image,
        description="synthetic_terrain_products",
        folder="terrain",
        fileNamePrefix="synthetic_terrain_products",
        region=roi,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )
