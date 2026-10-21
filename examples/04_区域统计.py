region={"type":"Polygon","coordinates":[[[113.55,22.30],[113.57,22.30],[113.57,22.32],[113.55,22.32],[113.55,22.30]]]}
cube = connection.load_collection("sentinel-2-l2a", temporal_extent=["2024-01-01","2024-02-01"],
    spatial_extent={"west":113.55,"south":22.30,"east":113.57,"north":22.32}, bands=["red","nir"])
series = cube.ndvi(nir="nir",red="red").aggregate_spatial(geometries=region,reducer="mean")
job = series.save_result("CSV").create_job(title="研究区 NDVI 时间序列")
job.start_job()
print(job.job_id)
