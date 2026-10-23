# 本地 DEM 与地形计算

EE 目录增加本地 ID `cop-dem-glo-30`，仅接受新入库流程生成的
`cop-dem-glo-30/v1` 数据合同。它有一个单位为米的 `elevation` 波段。
数据必须先同步到本机；表达式编译不会下载影像，也不会查询 Google。
这是目录与入库适配，未增加新的 EE 算法名称。

```python
dem = ee.ImageCollection('cop-dem-glo-30').filterBounds(region)
elevation = dem.first().select('elevation')
products = ee.Terrain.products(elevation)
Map.addLayer(products.select('slope'), {'min': 0, 'max': 60}, '坡度')
```

`first()` 选择一幅实际入库的瓦片，不自动拼接其他瓦片。
空查询、缺失的波段、未通过合同检查的条目会明确失败。
相邻像元缺失时，地形结果保持 NoData；不填补边界。
完整示例见 [示例 51](../../examples/51_GEE_python_local_dem.py)。
导出需明确指定以米为单位的投影 CRS 和分辨率，以满足现有像元预算检查；
输出重投影在地形计算之后进行，不能改变高程源像元的距离定义。

## 数据合同

- 来源产品固定为 `cop-dem-glo-30`，保存源条目 ID、原始 STAC JSON
  摘要、请求范围及可取得的源版本。没有供应方版本号时保留未知状态，
  不把内部摘要称为产品发布版本。
- 单波段 GeoTIFF 按实际原生网格裁切，不先重投影。记录实际 CRS、
  六参数仿射变换、形状、覆盖范围和输出 SHA-256；单次裁切最多四百万像元。
- 源 scale/offset 只应用一次；标准化资产明确声明 scale=1、offset=0、
  单位 m、Float32 与 NaN NoData。保留源掩膜，合法的 0 和 -9999 不变成缺测。
  非有限有效值、溢出、冲突的尺度或不支持的单位会拒绝。
  STAC 与 TIFF 同时声明 NoData 时须一致；仅 STAC 声明的缺测值会加入掩膜。
  支持至多 32 位的原始整数以及 Float32/Float64；拒绝复数和全部 64 位整型，
  防止先转 Float64 时丢失低位，再被 scale/offset 放大为错误结果。
- 明确记录 EGM2008 高程基准，以及“云掩膜不适用”。
  供应方时间必须存在且含时区；沿用其时间标签，不把标签解释成逐像元拍摄日期。
- 编译器只检查已提供的有界元数据，不读取文件或执行任意代码。
  合同标记不是安全凭证；权限、物理文件边界、任务快照和运行沙箱继续由现有模块执行。
  元数据校验计入原有 50,000 工作预算，进程图仍受 500 节点限制。

本版在执行集合筛选前校验当前快照的全部 DEM 条目；大目录不能靠
`filterBounds` 绕过这项开销。129 个坐标的固定合成条目，单条合同检查消耗
1,488 个工作单位，实际字段和后续表达式还会继续计费。因此当前通常只能
处理几十条这种密集轮廓记录，超限会拒绝，不能据此宣称支持全球 DEM 目录。
后续需要在保持相同预算的前提下改进目录查询与校验方式。

## 版本与迁移边界

旧 DEM 条目没有这份合同，不会因修改集合标记而自动被放行。
需要管理员按已有同步配置重新入库，生成新的不可变条目和 COG；
同一源 ID 与请求范围的新版本发布后，旧版本不再进入新任务。
原文件、历史任务快照和结果保留。其他仍活动的旧条目也需要重新同步或按
正常管理流程下架。开发和合成验收不会自动执行这项操作。

不注册 `COPERNICUS/DEM/GLO30` 或新版 Google 别名。
[Google 目录](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30)
包含多个质量波段并说明版本替换；本地单高程波段和有限覆盖不能替代该目录。
[供应方 STAC 集合](https://planetarycomputer.microsoft.com/api/stac/v1/collections/cop-dem-glo-30)
说明这是包含建筑和植被的地表模型，分析时不能默认它是裸土地形。
任意上传的 GeoTIFF、Landsat 和 ERA5 不会因此自动获得 EE 准入。

## 验证范围

可重复的合成验证分别检查官方 Python/JS 客户端图、目录拒绝条件、
真实 GeoTIFF 标准化、原生 GeoTrellis 地形内核以及实际结果文件读回。
最终计数与误差见 [第 46 批报告](../../reports/gee-python-wave46.json)。
这是可信组件间的文件链路；完整 Spark 作业、服务部署、浏览器操作、
私人真实 DEM 和 Google 同数据数值对照仍需独立验收。
度量与阴影规则沿用 [地形合同](terrain.md) 和 [原生数值说明](terrain-native.md)。
