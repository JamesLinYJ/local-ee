# 几何范围与区域模型

`Geometry.bounds(maxError=None, proj=None)` 和
`Feature.bounds(maxError=None, proj=None)` 支持有限 EPSG:4326 输入。
省略／空投影使用 EPSG:4326，显式 `proj='EPSG:4326'` 进入相同路径。
这是新增的本地计算能力；官方客户端能够序列化、后端能计算和 Google 结果等价分别记录。

```python
import ee

# 保留默认球面边，范围需要计入大圆弧的纬度极值。
outline = ee.Geometry.Polygon([
    [[-10, 70], [10, 70], [10, 75], [-10, 75], [-10, 70]]
])
extent = outline.bounds()
print(extent.getInfo())

# 本地影像足迹由目录提供，仍保留其真实平面模型。
image = ee.ImageCollection('sentinel-2-l2a').first()
local_extent = image.geometry().bounds()
clipped = image.clip(local_extent)

# Feature 返回 Feature，本地政策保留左侧 ID 和属性。
feature = ee.Feature(outline, {'site': 'example'})
bounded_feature = feature.bounds()
```

## 输入、计算与输出

| 情形 | 当前行为 |
| --- | --- |
| 有面积的有限平面输入 | 计算实际坐标极值 |
| 同一球面模型的有限输入 | 固定 S2 内核计算弧及内部的包络，不用顶点极值代替曲线极值 |
| 普通非跨日期线包络 | 返回 EPSG:4326 坐标对齐的平面 Polygon |
| 有面积的全经度／触极包络 | 返回经度从 -180 到 180 的有限平面矩形 |
| 省略、空或显式 EPSG:4326 投影 | 同一路径，不要求用户改写为非默认参数 |
| 有效 `maxError`／`ErrorMargin` | 在已支持的无重投影路径校验；不据此声称通用误差传播 |
| 空、零宽或零高的结果 | 明确拒绝，公开编码尚未确认 |
| 跨日期线、混合边模型、其他 CRS | 明确拒绝，尚未实现所需编码或变换 |

返回矩形明确标记 `geodesic=False`、`evenOdd=True`，可以进入已有平面消费者。
这是本地输出政策；官方说明没有完全规定这些公开标志及 Feature ID／属性保留细节，
尚无 Google 对照，不宣称逐字段相同。Point／MultiPoint 没有边，不会凭空产生球面边模型。

原始输入先在共享预算内重新校验并复制。S2 调用前预留输入、原生和完整结果成本；
输出解码、矩形构造和公开映射不能靠临时预算绕开父账本。
原 50000 工作量、几何深度／坐标／子几何上限与图规模限制不变。

分离球面分量的经度范围通过原始角度区间排序／合并后，取最大空隙的补区间，
避免逐次扩张导致输入顺序影响结果。保留极小坐标差异，不用角度平移或 epsilon 合并来消除差别。
这只处理包络；跨日期线包络的公开 GeoJSON 编码仍不支持。

## 裁切、统计与导出边界

`Image.clip`、`Image.reduceRegion` 及服务的导出／查询区域使用调用方的几何来源：
用户通过官方 EE API 提交的无标志几何保留 EE 默认球面语义；字典取值、Feature 包装
和集合嵌套不能洗掉该模型。显式坐标系、`evenOdd` 和有效边模型均要重新校验，
不能只检查一个 `geodesic` 字段就交给 GEOS。

已知本地 STAC 足迹仍按原始 RFC7946 平面规则处理。默认值施加在实际无标志的叶几何，
不能在 GeometryCollection 根上添加平面标志来覆盖已有的类型化球面子几何。
输入、IR 和公开映射各自拥有独立副本。

Feature 包装上的 `geodesic`、`evenOdd`、`crs` 属于当前不支持的模型字段，
会明确拒绝；普通 Feature 的模型写在其 `geometry` 内。
这是本地拒绝政策，不把任意外来成员的处理推断为 Google 行为，
也不让包装字段覆盖子几何或将默认球面值改成平面。

球面区域进入尚未实现的栅格消费者时明确报错。将旧错误接受改为拒绝是正确性修复，
不计为新增算法兼容。球面部分像元裁切、线的抗锯齿掩膜及区域带权统计仍未完成；
像元中心判断不能证明这些功能。真实带权覆盖、量化边界和 Google 结果仍是独立缺口。

## 验证范围

验证以固定双客户端原始表达式、独立坐标／大圆弧参考、版本化合成目录、
真实本地 S2 组件和物理要素 CSV 写出读回为主。目录别名修正等测试夹具校准保留原始失败，
不算新增数据集支持。浏览器、完整 Spark 批任务、私有真实影像及生产部署另行验收。
不自动调用 Google、登录或消耗 GEE 配额；只有本地参考无法可靠确认的复杂算法才另行讨论。

最终完整回归为 **6668 passed／27 skipped**，源码／样本38项摘要稳定，前端11项、类型与临时构建通过。
原始21案例在每个SDK各25次输入验证为16计算／9明确拒绝；另有真实本地内核、独立弧参考、
288种分量排列和两行物理CSV读回。日期线单点 +180／-180 的字面差异按精确周期同一性另行裁定，
原始失败记录保留。既有3项严格binary64关联／往返问题在本批重现，仍未修复，不能以容差通过代替。

官方合同见 [Geometry.bounds](https://developers.google.com/earth-engine/apidocs/ee-geometry-bounds)、
[Feature.bounds](https://developers.google.com/earth-engine/apidocs/ee-feature-bounds)
及[带权归约](https://developers.google.com/earth-engine/guides/reducers_weighting)。
本批具体证据、数值范围和剩余限制见 [第六十九批报告](../../reports/gee-python-wave69.json)。
