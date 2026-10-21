# 语法与 API 文档

GEE JavaScript 的对应语法、运行链路、验证等级和已知限制见 [GEE 兼容文档](gee-compatibility.md)。下面保留 Python/openEO 参考。

内容与工作台顶部“语法文档”一致；本站提供 Python 3.11 和 openEO Python 客户端。算子参数以本机 `/openeo/1.2/processes` 返回值为准，不自动访问外部文档。

## 脚本怎样运行

编辑器运行标准 Python 3.11。变量 connection 已由运行器连接并认证到本机 openEO API，无需填写密码。Python 脚本最长运行 120 秒，负责构建和提交计算图。影像计算由独立 GeoTrellis 任务执行，默认同时运行一个重任务。任务面板中的 Python 和 GeoTrellis 是两个不同阶段。

```python
print(connection.list_collection_ids())
print(connection.describe_collection("sentinel-2-l2a"))
```

## 变量、数字、字符串和注释

用 = 赋值；# 后是注释。字符串用单引号或双引号，f 字符串可插入变量。Python 区分大小写。缺失值用 None，布尔值用 True / False。

```python
# 注释不会执行
year = 2024
threshold = 0.3
collection_id = "sentinel-2-l2a"
print(f"分析 {year} 年的 {collection_id}")
```

## 列表、字典与索引

列表用于波段、日期等有序值。字典用键值对表示研究区等参数。索引从 0 开始，切片 [start:end] 不包含 end。

```python
bands = ["red", "nir"]
dates = ["2024-01-01", "2024-02-01"]
aoi = {"west": 113.55, "south": 22.30, "east": 113.57, "north": 22.32}
print(bands[0], aoi["west"])
```

## 条件、循环与缩进

if / elif / else 作条件判断，for 遍历数据。冒号后开始代码块，用 4 个空格缩进。不要把 Tab 与空格混用。循环提交会创建多个任务，建议先小范围测试。

```python
for year in [2023, 2024]:
    if year == 2024:
        print("当前年份", year)
    else:
        print("历史年份", year)
```

## 函数、参数与返回值

def 定义函数，return 返回结果。调用时可用关键字参数，让范围和单位更清楚。默认参数放在必填参数之后。

```python
def make_extent(west, south, east, north):
    return {"west": west, "south": south, "east": east, "north": north}

aoi = make_extent(west=113.55, south=22.30, east=113.57, north=22.32)
```

## 导入、异常与输出

import 导入已安装的模块。try / except 捕获预期错误；未捕获异常会使 Python 任务失败，完整信息在日志中。print 输出到控制台。运行容器不能联网安装新软件包。

```python
from datetime import date
try:
    metadata = connection.describe_collection("sentinel-2-l2a")
    print(metadata["id"], date.today())
except Exception as error:
    print(type(error).__name__, str(error))
    raise
```

## 延迟计算与进程图

load_collection、ndvi、reduce_dimension 等方法构建计算图，调用时不会读取全部像素。create_job() 将计算图保存到后端，start_job() 才进入队列。不要用普通 Python if 判断一个 DataCube。不要把 DataCube 当成 NumPy 数组。GEE 的 ee.* 脚本不能直接运行。

```python
cube = connection.load_collection(
    "sentinel-2-l2a",
    spatial_extent={"west":113.55,"south":22.30,"east":113.57,"north":22.32},
    temporal_extent=["2024-01-01","2024-02-01"],
    bands=["red","nir"]
)
print(cube.flat_graph())
```

## connection.load_collection()

必填 collection_id 为左侧数据集 ID。spatial_extent 使用 west/south/east/north；默认坐标系 EPSG:4326，单位为度。temporal_extent 为 [开始, 结束]，结束点不包含。bands 是本地数据集波段名，不一定与供应商原始名称相同。只能选择已入库的数据。

```python
cube = connection.load_collection(
    "sentinel-2-l2a",
    spatial_extent={"west":113.55,"south":22.30,"east":113.57,"north":22.32},
    temporal_extent=["2024-01-01","2024-02-01"],
    bands=["red","nir"]
)
```

## 筛选波段、时间与范围

filter_bands() 筛选波段；filter_temporal() 缩小日期范围；filter_bbox() 缩小空间范围。筛选操作不会把尚未同步的数据从公网补回来。

```python
subset = cube.filter_bands(["red","nir"])
subset = subset.filter_temporal("2024-01-10", "2024-01-20")
subset = subset.filter_bbox(west=113.55, south=22.30, east=113.56, north=22.31)
```

## 波段运算、NDVI 与 NDWI

band() 选择单波段。DataCube 支持 +、-、*、/。NDVI=(NIR−Red)/(NIR+Red)；NDWI=(Green−NIR)/(Green+NIR)。反射率已按源数据的 scale/offset 转换，不要再次乘 0.0001。分母为零或无效输入应作为 NoData。

```python
ndvi = cube.ndvi(nir="nir", red="red")
# NDWI 需要先加载 green 与 nir 波段：
# green, nir = cube.band("green"), cube.band("nir")
# ndwi = (green - nir) / (green + nir)
```

## 时间合成与维度归约

reduce_dimension() 在一个维度上计算 mean、median、min、max、sum 等。t 是时间维度，bands 是波段维度。mean_time() 是按 t 计算均值的快捷方法。云和缺测处理会影响结果，时间合成前请先确认输入数据的掩膜规则。

```python
composite = cube.reduce_dimension(dimension="t", reducer="median")
mean_image = cube.mean_time()
```

## 回调表达式与 lambda

openEO 的 lambda 回调构建后端表达式，函数参数通常是 ProcessBuilder。只能使用受支持的 openEO 算子，不能在 lambda 里随意调用 Python 库。UDF（run_udf）暂不开放；网页 Python 脚本运行和像素级 UDF 是两种不同功能。

```python
scaled = cube.apply(lambda x: x * 2 + 1)
from openeo.processes import sum as process_sum
monthly = cube.aggregate_temporal_period(
    "month", reducer=lambda data: process_sum(data, ignore_nodata=False)
)
```

## 区域统计与 GeoJSON

aggregate_spatial() 接受 GeoJSON 几何，reducer="mean" 等指定聚合。GeoJSON 坐标顺序是经度、纬度，Polygon 环必须闭合。输出为区域时间序列，可保存 CSV。界面导入研究区目前把其包围盒用于数据加载；精确多边形统计应把几何传入本方法。

```python
region = {"type":"Polygon", "coordinates":[[
    [113.55,22.30],[113.57,22.30],[113.57,22.32],
    [113.55,22.32],[113.55,22.30]
]]}
series = cube.aggregate_spatial(geometries=region, reducer="mean")
```

## 提交、状态、取消和日志

create_job(title=...) 创建批处理，start_job() 开始。describe_job() 返回状态，logs() 返回日志，stop_job() 取消。网页控制台也可查看。任务失败后使用面板“重新提交”，新任务拥有独立 ID 和输出目录。不要在 120 秒的脚本里长时间等待重任务。

```python
job = cube.save_result("GTiff").create_job(title="遥感分析")
job.start_job()
print("任务 ID:", job.job_id)
print(job.describe_job()["status"])
# 以后可用 job = connection.job("任务 ID")
# job.stop_job()
```

## GeoTIFF、NetCDF、CSV

GTiff 用于栅格影像，NetCDF 用于多时相数据立方体，CSV 用于区域统计的表格结果。任务完成后，从任务面板下载。GeoTIFF 可点击“显示地图”，色带最小/最大值仅改变显示，不修改结果数据。像素查询返回原始数值。

```python
job = cube.save_result("NetCDF").create_job(title="多时相影像")
job.start_job()
# 区域统计可用 series.save_result("CSV")
```

## ERA5-Land 单位与时间

本地 temperature 为 UTC 日均温，单位摄氏度，由 00–23 UTC 共 24 个样本计算；缺小时则该日 NoData。precipitation 为 UTC 日累计 mm，取次日 00 UTC 的原始累计值。月降水对完整月份的日累计求和，不能把原始累计小时值直接相加。没有 CDS 凭据时，ERA5-Land 不会自动入库。

```python
cube = connection.load_collection("era5-land",
    temporal_extent=["2024-01-01","2024-02-01"],
    spatial_extent={"west":113.5,"south":22.2,"east":113.8,"north":22.5},
    bands=["precipitation"])
```

## 反射率、云掩膜与 NoData

Sentinel-2 使用 Earth Search Collection 1，按资产元数据 scale/offset 转换反射率；旧 L2A 源因偏移元数据歧义不接收，保留 SCL 分类 4、5、6、7。Landsat C2 L2 使用 scale=0.0000275、offset=−0.2（以资产元数据优先），排除 QA_PIXEL 的 fill/cloud/shadow/snow 等位及 QA_RADSAT 饱和像素。标准化 COG 的 NoData 为 −9999。NoData 不等于 0，区域统计的有效像素数应单独检查。

## 常见错误与当前边界

CollectionNotFound：数据尚未同步或 ID 错误；空查询：范围/日期没有本地影像；全云：查询有影像，但掩膜后没有有效像素；ProcessGraphInvalid：用了本站未支持的算子或远程 namespace；超时/内存超限：缩小范围，分时段提交。脚本不能访问公网、宿主机文件和供应方凭据。任务服务重启后会继续追踪已存在的运行容器，容器丢失会明确标记失败。
