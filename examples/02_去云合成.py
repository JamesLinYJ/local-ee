cube = connection.load_collection(
    "sentinel-2-l2a",
    spatial_extent={"west":113.55,"south":22.30,"east":113.57,"north":22.32},
    temporal_extent=["2024-01-01", "2024-02-01"], bands=["red","green","blue"]
)
# 入库后的 NoData 已包含云、阴影、雪、饱和及无效像素。
composite = cube.reduce_dimension(dimension="t", reducer="median")
job = composite.save_result("GTiff").create_job(title="去云真彩色中值合成")
job.start_job()
print(job.job_id)
