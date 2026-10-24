# 默认球面几何

Python 和 JavaScript 继续使用固定版本官方客户端。`Geometry`／内联 `Feature` 的
contains、containedIn、intersects、disjoint、intersection、union、difference、
symmetricDifference 在省略或传入空 `proj` 时，走本地 S2 球面计算。
本页描述有限支持和剩余差异，不表示整个 GEE 几何、栅格或投影接口已经兼容。

```python
left = ee.Geometry.Polygon([[
    [170, -10], [-170, -10], [-170, 10], [170, 10], [170, -10]
]])
right = ee.Geometry.Polygon([[
    [175, -5], [-175, -5], [-175, 5], [175, 5], [175, -5]
]])
intersection = left.intersection(right)
inside = left.contains(ee.Geometry.Point([179, 0]))
features = ee.FeatureCollection([
    ee.Feature(intersection, {'name': 'intersection'})
])
task = ee.batch.Export.table.toDrive(features, 'spherical_roi', fileFormat='CSV')
task.start()
```

JavaScript 对应写法为 `left.intersection(right)`；不需要添加自定义语言或改成
`geodesic:false`。示例 [66](../../examples/66_GEE_python_spherical_geometry.py) 与
[JS 20](../../examples/javascript/20_球面几何.js) 使用固定合成样本，不读取 Google 数据。

## 默认值与表示

- 数字坐标默认 EPSG:4326、`geodesic=true`、`evenOdd=true`。官方客户端常省略
  `geodesic`，本地保留其有效默认值，不因此改用平面几何。
- 支持测地线点、线、多边形、孔洞、跨日期变更线、极区及有限几何集合。
  `evenOdd=false` 使用球面左侧内部规则，反转外环可改变其覆盖区域。
- 集合显式标志给未显式指定的子项提供默认值；子项显式标志优先。
  同一对象混用平面与球面边，不能通过未实现的变换自动合并。
- 空结果是真实空 `GeometryCollection`；点、线和多边形交集保留实际维度。
  Point／MultiPoint 的公开结果不添加 SDK 不接受的边／内部参数；线只公开边类型，
  多边形公开边和内部规则，私有元数据仍保留有效模型。
- Feature 结果只继承左要素的属性和现有本地身份规则；不复制右属性。

显式 `proj='EPSG:4326'` 仍是经纬度平面分支，要求明确直线边；见
[平面几何合同](geometry-binary.md)。它不能代替省略投影时的球面分支。

## 精度与未解决问题

本地采用 S2 的 CLOSED 边界模型和精确 binary64 S2 判定，不声称这与 Google
服务的全部边界／舍入规则相同。这里的“精确”针对已转换的 S2 向量，不能推广为
经纬度到球面及公开结果往返都无误差。

独立期望的 55 项原生控制有 52 项通过，以下 3 项仍不满足严格期望：

1. 多边形 `[0,0]–[2,2]` 与经度 2 的长线相交，输出端点可为
   `[1.9999999999999993, 1.9999999999999993]`。
2. 字面量 `Point([2,2])` 与 `LineString([[2,-1],[2,3]])` 的精确 S2 判定可为不相交。
3. 新算交点输出为经纬度后，重建的点不一定被精确判定为仍位于两条原线上。

第一项的观察坐标误差为 `6.66e-16°`，合成流程使用明确 `2e-14°` 数值容差；
这项数值通过没有消除后两项关联问题。原始失败记录保留，没有用吸附或模糊相等
合并近邻点；`1e-13°` 间隔的不同点仍保持不同。依赖库相同、算子同名以及本地
合成验证均不构成 Google 同数据对照。

另有以下接口缺口：

- 几何二元操作的非空 `maxError`、其他 CRS、平面边转球面与一般重投影仍未实现。有限空间筛选／内联合并可消费已验证的 ErrorMargin，但仅限无需变换的路径，见[空间筛选](spatial-selection.md)。
- `Geometry`／`Feature` 的 area、length、perimeter 和 distance 尚未实现。六条官方默认度量表达式的实际拒绝记录保存在[版本化探针](../../tests/fixtures/ee-measurement-wave62-before-v1.json)。官方指南把默认面积／周长计算描述为 WGS84 椭球；distance 的 `spherical=false` 默认也要求考虑扁率，不能直接以 S2 固定球半径乘角度来宣称默认兼容。后续优先采用本地独立椭球参考，补齐边模型、孔洞／大区域、分量相加及投影合同。[官方几何度量说明](https://developers.google.com/earth-engine/guides/geometry_visualization_info)、[distance 参数](https://developers.google.com/earth-engine/apidocs/ee-geometry-distance)。
- 跨日期变更线的 BBox 构造；不要把它与已支持的测地线 Polygon 混为一谈。
- 无边界完整球面的公开 GEE GeoJSON 编码：只保留独立内部值，公开 JSON／CSV
  明确失败，不伪装为空几何。
- 显式球面结果尚不能进入旧版 Image.clip、reduceRegion、空间筛选或平面足迹合并，
  这些消费者在 GEOS 前拒绝。原先不带公开边标志的栅格输入路径仍按平面处理，
  不能据其成功声称 GEE 默认测地线裁切兼容。球面掩膜、投影及误差传播仍需继续实现。

## 验证策略

日常回归以本地独立参考和可信合成流程为主，不自动调用GEE，也不把在线配额作为开发前置。只有非常复杂、文档和独立参考无法可靠判定的算法才另行讨论少量远端对照；已有可信GEE输出可保存后离线复用。官方客户端序列化、本地正确性和真实Google等价分别报告；当前本批没有使用Google云端计算结果作为基准。

## 本地构建与资源边界

S2 0.14.0 与 Abseil 20250814.1 的源码提交、下载摘要和构建选项固定在
[`dependencies.lock.json`](../../native/s2/dependencies.lock.json)。构建只生成项目自有
动态库，不安装系统包、不修改 Python 虚拟环境，也不启动容器或虚拟机。

```sh
.venv/bin/python scripts/build_s2_adapter.py \
  --work-dir work/s2-build \
  --output-dir native/s2/artifacts --jobs 4
```

输出目录须不存在。已验证的下载可以通过同一工作目录的 `--offline` 重建到另一个
新目录；更新时保留当前产物，先在新目录构建、验证后再切换。运行时绝不下载依赖。
缺少产物、摘要不符、源文件变化、许可证缺失、符号链接或平台不符均停止加载。
产物附带 S2 LICENSE／NOTICE、Abseil LICENSE 和摘要。Linux CI 使用相同脚本单独构建；
本机原生组件检查不等于平台部署或完整 Spark 验收。

输入最多 10000 个坐标、1000 个集合子项、16 层。归一化、两两相互作用、输出增长和
复制均在原有共享 50000 工作预算内预充；可接受规模通常远小于坐标硬上限。
原生层再次校验计数、有限值、几何合法性、缓冲区和独立调用预算。
64 MiB 限制仅覆盖 S2 所跟踪的工作分配，不是整个进程的严格 RSS 上限。
CSV 保持原有 1000 行、256 列、50000 单元和 1 MB 限制，所有球面行先统一预检计费。
球面曲线的表格范围采用保守全球范围，紧致曲线 bbox 尚未实现。

来源：[GEE Polygon](https://developers.google.com/earth-engine/apidocs/ee-geometry-polygon)、
[几何操作](https://developers.google.com/earth-engine/guides/geometric_operations)、
[S2 源码](https://github.com/google/s2geometry/tree/v0.14.0)。
