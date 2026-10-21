cube = connection.load_collection(
    "sentinel-2-l2a",
    spatial_extent={"west":113.55,"south":22.30,"east":113.57,"north":22.32},
    temporal_extent=["2024-01-01", "2024-02-01"], bands=["green","nir"]
)
green = cube.band("green")
nir = cube.band("nir")
ndwi = ((green-nir)/(green+nir)).mean_time()
job = ndwi.save_result("GTiff").create_job(title="NDWI 水体指数")
job.start_job()
print(job.job_id)
