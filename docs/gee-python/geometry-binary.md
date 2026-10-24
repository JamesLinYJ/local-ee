# GEE 几何与要素二元运算

## 当前球面路径

省略或空 `proj` 的有限测地线几何已另接本地 S2；默认值、数值精度和下游缺口见
[默认球面几何](spherical-geometry.md)。下文保留显式 EPSG:4326 的平面分支合同，
不再代表全部几何二元操作的当前支持范围。

继续使用官方 Python／JavaScript 客户端的写法，不增加本地平台语法。本批实现以下同名方法的有限平面路径：

| 返回值 | Geometry 与 Feature 上的方法 |
| --- | --- |
| Boolean | `contains`、`containedIn`、`intersects`、`disjoint` |
| Geometry／Feature | `intersection`、`union`、`difference`、`symmetricDifference` |

所有方法保留官方 `left`、`right`、`maxError`、`proj` 参数名。Feature 的实际接收者目前限于有几何的内联要素；Image 和动态运行时 Element 重载尚未实现。

## 当前可执行的官方写法

```python
projection = ee.Projection('EPSG:4326')
study = ee.Geometry.Rectangle(
    [0, 0, 4, 4], proj=projection, geodesic=False,
)
excluded = ee.Geometry.Rectangle(
    [1, 1, 3, 3], proj=projection, geodesic=False,
)
roi = study.difference(excluded, proj=projection)
clipped = image.clip(roi)
intersects = study.intersects(excluded, proj=projection)
feature = ee.Feature(study, {'name': 'study'})
remainder = feature.difference(ee.Feature(excluded), proj=projection)
```

这一路径是在经纬度坐标平面上运算，没有转换到米单位。`proj` 必须显式为 `EPSG:4326`；有边的每个几何组件必须能证明 `geodesic=False`。点和空几何没有边。省略或传入 `None` 的 `maxError` 可用，非空误差对象、其他坐标系、球面边和 `evenOdd=False` 暂不支持。输入采用有效、有限的二维 GeoJSON 子集，不替代 GEE 全部几何构造语义。

## 投影与默认值

GEE 几何二元操作省略 `proj` 时使用球面坐标系统；普通数值坐标 Polygon 默认使用测地线边。显式指定 `EPSG:4326` 不会自动把球面弧变成经纬度直线。见官方 [intersection 参数](https://developers.google.com/earth-engine/apidocs/ee-geometry-intersection)、[Polygon 构造](https://developers.google.com/earth-engine/apidocs/ee-geometry-polygon)及[几何运算](https://developers.google.com/earth-engine/guides/geometric_operations)。

下面的正常默认写法现已接入固定 S2 的有限球面路径；需先构建本地适配器：

```python
result = ee.Geometry.Polygon(coordinates).intersection(other)
```

这不表示全部重载、投影或下游栅格已经兼容。非空误差、一般重投影、球面栅格消费者和3项严格精度控制仍有缺口，见[球面合同](spherical-geometry.md)。平面门禁与解码使用相同优先级：显式公开边标志、父集合继承、内部默认值；旧内部元数据不能让球面边进入GEOS。有边组件可继承明确的 `geodesic=False`，点和空几何不制造边模型冲突。

## 结果、边界与预算

- 要素叠加结果保留左要素的独立属性副本，忽略右侧属性。实际左 ID 按已有本地身份规则保留；这条 ID 政策未完成 Google 对照。
- 空结果返回有效的空 GeometryCollection；线或点交集保持实际维度。现有 `Image.clip` 只接受 Polygon／MultiPolygon，其他维度明确拒绝。
- 新生成的平面边几何保留 `geodesic: false`，Point／MultiPoint省略客户端不接受的边／内部标志；内部仍保留独立元数据。输入与各次输出不共享可变坐标或属性。
- `contains` 使用本地 GEOS 的内部／边界定义：仅在边界上的点不算包含，`intersects` 可以为真。见 [Shapely contains 定义](https://shapely.readthedocs.io/en/stable/reference/shapely.contains.html)。这不是 Google 边界规则对照的结果。
- 几何操作在 GEOS 构造和输出分配前预检输入、跨／内部候选交互、环闭合和输出增长；原50000工作、10000坐标、1000子几何及16层限制保持。形状有效不保证复杂组合一定能通过资源准入。

## 示例与验证范围

运行 [Python 示例65](../../examples/65_GEE_python_roi_geometry.py) 或参考 [JS 示例19](../../examples/javascript/19_研究区叠加与排除.js)。样本是仓库中声明的两景 Sentinel-2 合成数据，包含研究区、内部排除区、独立像元掩膜／NDVI预期与要素 CSV 读回：

```sh
.venv/bin/python examples/65_GEE_python_roi_geometry.py
.venv/bin/python -m pytest -q tests/test_ee_roi_geometry_workflow.py
```

编译、合成图数值和可信表格文件读回分别记录；没有把它们作为新增原生 GeoTrellis、完整 Spark、部署、浏览器或 Google 同数据验收。
