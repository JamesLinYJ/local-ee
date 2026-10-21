from openeo.processes import sum as process_sum
# 入库产品 precipitation 是 UTC 日累计 mm；这里不再对原始累计小时值求和。
# 月统计前须确保完整月份已经入库，缺测值按 NoData 传播。
cube=connection.load_collection("era5-land",temporal_extent=["2024-01-01","2024-02-01"],
    spatial_extent={"west":113.5,"south":22.2,"east":113.8,"north":22.5},bands=["precipitation"])
daily=cube.save_result("NetCDF").create_job(title="ERA5-Land 日降水 mm")
daily.start_job()
monthly=cube.aggregate_temporal_period("month",reducer=lambda data:process_sum(data,ignore_nodata=False))
job=monthly.save_result("NetCDF").create_job(title="ERA5-Land 月降水 mm")
job.start_job()
print("日产品:",daily.job_id,"月产品:",job.job_id)
