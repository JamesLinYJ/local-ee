# 空间筛选与合并研究区

支持固定官方 Python／JavaScript 客户端的有限内联要素筛选及合并。默认经纬度几何
保留测地线边，通过项目本地 S2 计算；显式平面几何保留 GEOS 路径。
这不是栅格裁切、通用重投影或 Google 数值等价验收。

```python
roi = ee.Geometry.Polygon([
    [[170, -5], [-170, -5], [-170, 5], [170, 5], [170, -5]]
])
sites = ee.FeatureCollection([
    ee.Feature(ee.Geometry.Point([179, 0]), {"site": "east"}),
    ee.Feature(ee.Geometry.Point([-179, 0]), {"site": "west"}),
    ee.Feature(ee.Geometry.Point([0, 0]), {"site": "origin"}),
])
selected = sites.filterBounds(roi)  # east、west
merged = ee.FeatureCollection([ee.Feature(roi)]).geometry()
```

`filterBounds` 是官方客户端辅助方法，序列化为 `Filter.intersects`，其 ROI 可以被
`Feature` 包装。兼容层读取包装内的实际几何，保留有效默认边模型，不把缺少公开
`geodesic` 字段解释为平面。跨日期变更线、极区和高纬弯曲边界由同一路径处理。

## 参数与数据模型

`Filter.intersects` 支持 `leftField`／`leftValue` 与 `rightField`／`rightValue`，
每一侧恰好一个非空参数。`.all`／`.geo` 读取当前记录几何，其他字段读取有限的
顶层几何属性。支持交换左右参数、字段与字段、字面值与字面值。缺失／空记录几何
不匹配；无效的字面 ROI 即使在空集合或未命中的逻辑分支中也必须拒绝。
这些能力仅用于内联要素及目录记录，不据此开放二元 Join、取样表或运行时空间筛选。

`Collection.geometry` 的官方参数只有 `collection` 和可选 `maxError`。
内联集合忽略 null 几何行，合并实际分量并保留维度、孔洞、边模型及独立坐标副本。
所有有边分量必须具有相同 EPSG:4326 模型；子项的显式标志覆盖父项的继承默认值。
Point 和空几何不凭空引入曲线类型；即使只有一个球面 MultiPolygon，也执行区域归一化。
非法 OGC 平面 MultiPolygon 仍在准入时拒绝，独立合法平面 Features 可正常合并。
空／全 null 集合返回空 GeometryCollection 是明确的本地规则，尚无 Google 对照。
目录 ImageCollection 的 `.geometry()` 仍沿用原足迹路径，不属于这次合并实现。

**原始目录足迹与官方 EE 几何必须区分。** STAC 的未标记 GeoJSON 按 RFC7946 保留
经纬度直线边。它不会被偷偷改成大圆弧。因此默认球面多边形 ROI 与这类目录多边形
相交时，目前明确拒绝需要重投影的组合；此前这条路径曾静默返回平面结果。
真实平面 ROI 或没有边的 Point 可以与平面目录足迹运算。带明确边模型或内部类型的
输入保留原模型。不得为了通过测试改变数据足迹的科学解释。

目录中的派生裁切足迹复用同一有界平面交集：完整校验原始坐标、拓扑、CRS 和模型后
再运算，真实空集返回有限空 GeometryCollection。不能先裁掉非法输入，再把空结果
当作合法数据。合法空 Multi 几何保持可用，源记录保持不变。若旧 mapped clip 保留了
默认球面类型，它在平面足迹物化时也会明确拒绝；单独的旧无标记栅格路径仍有下述限制。

## ErrorMargin

固定签名的筛选默认误差为 0.1 米，集合合并默认为 0 米；官方客户端省略／null 参数
保持默认调用。显式 `ee.ErrorMargin(...)` 作为不透明类型保留，只由已经证明不需要
坐标变换的本批消费者接收。容差不会增加缓冲、改变边模型或选择平面算法。

构造器支持 `meters`、`projected` 和 `infinite`，负值取绝对值；非零米值须至少
0.001，绝对值达到 20000000 时归一化为无限误差。数值与字段仍须通过有限类型校验。
独立 ErrorMargin 不能作为 getInfo／CSV 属性输出，其他几何二元运算、Feature.geometry、
影像裁切等消费者仍保留各自的非空误差限制。没有实现通用误差传播或重投影。

## 验证与限制

公开[原表达式探针](../../tests/fixtures/ee-spatial-consumers-wave63-before-v1.json)包含
三条原先选错记录的筛选和三条合并检查。预期来自手写非边界点、独立单位向量绕数和
布尔集合关系；不以本实现产生的结果充当预期。双客户端组合、实际合成 CSV 写出和
官方 SDK 读回与真实 Google 结果分开报告。日常验证不调用 Google。

可运行的离线合成示例：[Python](../../examples/67_GEE_python_spatial_selection.py)、
[JavaScript](../../examples/javascript/21_球面筛选与研究区.js)。它们分别查询日期线／极区，
再合并两块高纬区域；完整四区域合并在当前共享工作预算中仍可能超限，未放宽上限。

输入、重复检查、复制、模型扫描、S2／GEOS 运算及输出继续使用原共享 50000 工作预算，
并保留 1000 行、10000 坐标、16 层和表格输出上限；大集合不保证在此预算内通过。
没有引入缓存、折线逼近、额外网络权限、依赖或原生库更新。

S2 的 CLOSED 和 GEOS 的边界规则仍是本地策略，已有三项严格 binary64 关联差异仍未解决。
球面像元掩膜、栅格统计、其他 CRS、混合曲线转换、完整球面公开编码和度量仍待完成。
旧未标记栅格输入仍走平面路径，不能当成默认 GEE 测地线裁切兼容。

参考：[Filter.intersects](https://developers.google.com/earth-engine/apidocs/ee-filter-intersects)、
[集合几何](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-geometry)、
[ErrorMargin](https://developers.google.com/earth-engine/apidocs/ee-errormargin)、
[GeoJSON 线段定义](https://www.rfc-editor.org/rfc/rfc7946#section-3.1.1)。
