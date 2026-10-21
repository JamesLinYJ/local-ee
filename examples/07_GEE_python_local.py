"""Official Earth Engine Python client, routed to the local workbench."""
import ee

# The workbench binds the official client to its local EE adapter.
ee.Initialize()

roi = ee.Geometry.Rectangle([113.55, 22.30, 113.57, 22.32])
images = (
    ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
    .filterBounds(roi)
    .filterDate("2024-01-01", "2024-02-01")
)
ndvi = images.map(
    lambda image: image.normalizedDifference(["B8", "B4"])
    .rename("NDVI")
    .copyProperties(image, ["system:time_start"])
).median().clip(roi)

Map.centerObject(roi, 13)
Map.addLayer(
    ndvi,
    {"min": 0, "max": 1, "palette": ["f4e5b9", "155b3b"]},
    "NDVI",
)

# `toDrive` keeps the official client method name; output stays in local results.
task = ee.batch.Export.image.toDrive(
    image=ndvi,
    description="local-ndvi",
    region=roi,
    scale=10,
    maxPixels=1e8,
)
task.start()
print("本地导出任务:", task.id)
