# Sentinel-2 的反射率缩放和 SCL 去云已在本地入库时完成。
# 修改范围和日期后运行；connection 由隔离运行器提供。
cube = connection.load_collection(
    "sentinel-2-l2a",
    spatial_extent={"west":113.55,"south":22.30,"east":113.57,"north":22.32},
    temporal_extent=["2024-01-01", "2024-02-01"],
    bands=["red", "nir"],
)
ndvi = cube.ndvi(nir="nir", red="red").mean_time()
job = ndvi.save_result("GTiff").create_job(title="Sentinel-2 月合成 NDVI")
job.start_job()
print("GeoTrellis 任务已提交:", job.job_id)
