# 需要先配置 CDS 凭据并同步 ERA5-Land。本地产品单位为摄氏度。
region={"type":"Polygon","coordinates":[[[113.5,22.2],[113.8,22.2],[113.8,22.5],[113.5,22.5],[113.5,22.2]]]}
cube=connection.load_collection("era5-land",temporal_extent=["2024-01-01","2024-02-01"],
    spatial_extent={"west":113.5,"south":22.2,"east":113.8,"north":22.5},bands=["temperature"])
job=cube.aggregate_spatial(region,"mean").save_result("CSV").create_job(title="ERA5-Land 日均温度")
job.start_job()
print(job.job_id)
