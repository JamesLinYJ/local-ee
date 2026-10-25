# Geometry／Feature 度量

使用固定官方 Python／JavaScript 客户端的 `area`、`length`、`perimeter` 和
`centroid`，参数继续为 `geometry`／`feature`、`maxError`、`proj`。
实现范围是有限内联 EPSG:4326 几何；数据源与栅格区域消费者保留各自限制。

```python
polygon = ee.Geometry.Polygon([[[0, 0], [90, 0], [0, 90], [0, 0]]])
area_m2 = polygon.area()
perimeter_m = polygon.perimeter()
center = polygon.centroid()

feature = ee.Feature(polygon, {'name': 'octant'})
measured = feature.set({'area_m2': feature.area(),
                        'perimeter_m': feature.perimeter()})
centroid_feature = measured.centroid()
```

示例：[Python](../../examples/75_GEE_python_geometry_measures.py)、
[JavaScript](../../examples/javascript/29_几何度量.js)。

## 边、投影和单位

| 调用 | 接受的实际边模型 | 数值含义 |
|---|---|---|
| 省略或空 `proj` | 默认／显式测地线，点无边模型 | WGS84 上的 m、m²；球面最高维加权质心 |
| 显式 `ee.Projection('EPSG:4326')` | 显式 `geodesic=False`，点无边模型 | 直线坐标的度、平方度及平面质心 |

测地线边保留球面大圆弧，在该曲线上按 WGS84 线元／面积元积分。
不能用固定球半径把 S2 角度直接转成米，也不能只把两个端点交给椭球最短路径算法，
后者会改变斜向边的实际曲线。此处是根据官方边模型和度量说明选择的本地实现；
Google 内部数值实现与容差尚未对照。
[官方边模型](https://developers.google.com/earth-engine/guides/geometries_planar_geodesic)、
[官方默认度量说明](https://developers.google.com/earth-engine/guides/geometry_visualization_info)。

WGS84 常量为 `a=6378137 m`、`f=1/298.257223563`。
每条实际选中边采用有界 Gauss–Legendre 积分及收敛检查；未收敛明确失败。
这是本地数值政策，不能作为严格误差证书。
面积修正使用 16 项偏心率级数，先解析消去相等的大项，避免相消放大舍入误差。
只有全部顶点距首顶点不超过 0.01 弧度、且不触及极区保护条件的局部环使用中心化积分；
其余使用光滑的直接积分。两条路径仍按每边 56 次采样预充，阈值是本地数值选择，
不会修改顶点、拓扑或独立参考的容差。
近对跖边、无法确定的球面扇分支及在 S2 中丢失身份的不同坐标也明确失败，
不会通过放宽相等规则来生成度量。
有效 `maxError`／`ErrorMargin` 仅在没有重投影的路径上校验；不会被解释为积分精度承诺。
平面转球面、球面转平面和其他 CRS 的变换继续明确拒绝。

## 分量、空值和质心

- `area` 只累加多边形面积；`length` 只累加线分量；`perimeter` 只累加多边形边界。
  多边形的 `length()` 为零。没有先求并集，重复或重叠分量分别计入。
  第七十二批接通显式平面重叠／重复 `MultiPolygon` 的原始官方客户端请求，
  每个完整 Polygon 连同孔洞分别校验，保留原坐标、分量顺序及重复次数。
  原16条请求沿用原数值期望通过，不再要求改成 `GeometryCollection`。
  该累加规则依据[官方 area 说明](https://developers.google.com/earth-engine/apidocs/ee-geometry-area)，
  不代表所有空间运算也使用分量累加。
- 孔洞与实际内部规则保留；不会为通过验证而擅自反转定向多边形。
  显式平面 `evenOdd=False` 仍不支持。
- 空几何及空 Feature 几何的三个标量为零，质心明确失败。
- 质心只使用最高维分量；混合集合里的点不会拉偏多边形质心。
  球面使用未归一化的 S2 加权向量，平面分量按实际面积／长度／点数加权。
- 精确抵消或数值上无法可靠确定方向的向量不产生假坐标；保留原始向量，报明确错误。
  数值不确定与数学上的零分开记录，不做吸附或 epsilon 合并。
- 单点质心返回新持有的原坐标；Feature 质心保留深复制的属性和已有身份。
  字段／ID 的本地政策不构成 Google 公共字段完全一致声明。

## 实现和验证边界

`geometry_measures` 负责路由和预充，`geometry_planar_measures` 负责原子平面分量，
`feature_geometry_measures` 保留 Feature 身份。`spherical_measures` 校验固定记录与质心。
原生 op10 返回八字段角度／向量记录；op11／12／13 分别返回面积、线长、周长的
`[1,value]`，避免未请求的面积积分失败阻塞线长或周长。
原有 op0–9 与单一 C ABI 导出保留。

`geometry_components` 负责官方几何构造、结构与属性传递的分量校验，复用
`planar_geometry_validation` 检查每个完整多边形；不合并重叠区，也不修复自交、
外部孔洞或相交孔洞。集合运算、目录 union、栅格、采样与使用共享表格的分类入口
仍各自检查整体拓扑，不能把可保存、可度量的几何直接当作其合法输入。纯数值
minimumDistance 训练可以保留不参与运算的分量几何，不因此获得空间运算能力。

封闭的 `local_ee_table` CSV 路径内部启用分量保留。共享 `columns`／`render_csv`
默认保持严格校验，输入数据不能选择配置。工作进程接收 JSON 后重新验证，
在进入首个 GEOS／S2 调用前，将整张表的结构／坐标／复制工作与实际球面叶节点
校验成本计入同一个50000上限；集合继承、类型化默认值和空球面集合也要计费。
这不是 GEOS CPU 时间或 RSS 保证。实际两行 CSV 保留原 MultiPolygon、身份及嵌套属性；
`.geo` 仍按既有公开映射补出有效 `evenOdd:true`。

输入扫描、S2 构造、选中边积分和输出复制都计入原共享 50000 步，
几何坐标／子项／深度和原生 64 MiB 跟踪内存限制保持。
跟踪内存不是进程 RSS 上限；依赖仍需预先本地构建，运行时不下载。
50000 是本地逻辑工作保护值，不是 GEE 限额，也没有按秒数标定。
2026-10-25 本机对三份冻结原式各重复5次，编译及静态几何求值的中位耗时为
WGS84 108.676 ms、平面 MultiPolygon 32.179 ms、GeometryCollection 36.185 ms；
不含 SDK 构造、栅格批任务或服务负载，不能据此推算其他公式的耗时。
生产容量仍需实际压测；管理员可配置的编译预算与独立任务时间／内存限额是后续工作。
共享第七十三批减少同一请求里的重复几何校验、计算和要素公开大小扫描，
三组原始完整公式保留相同输入、方法调用、列与独立参考后通过：

| 原始公式 | 行 × CSV列 | 编译工作量／50000 |
|---|---:|---:|
| WGS84，Geometry／Feature，省略及空投影 | 4 × 19 | 42876 |
| 显式平面 MultiPolygon | 6 × 13 | 45852 |
| 显式平面 GeometryCollection | 6 × 13 | 49708 |

上表使用官方 SDK 当次生成的字典遍历顺序；保存的同一规范请求按归档顺序重放为
42700／45588／49444。两种顺序均通过，数值和规范请求摘要一致，不将逻辑计数当作 CPU 指令数。

每次复用都重新扫描实际内容；数字类型、负零、选项有无和所有嵌套几何元数据参与匹配。
分量拓扑证明、数值结果和要素公开大小／复制成本分别保存，不能互相授权。
Feature ID 只缩小候选范围，返回属性与质心仍独立复制。严格整体拓扑校验不变；
已选原生组件的来源／产物检查保留。两个缓存合计最多64项、保守存储计数1MB，
不是进程 RSS 上限；扫描、匹配、存储和复制仍计费，没有扩大50000上限。

六份原始 Python／JavaScript 请求各自完成编译及独立数值对照；三份 Python 官方
getInfo／导出请求实际进入可信合成调度、worker 和表格引擎，CSV 已写出并逐列读回。
测试使用内存数据库／队列和替代启动器，未验证 HTTP、真实沙箱、Spark 或部署。
另有两行相同几何、不同 ID／嵌套属性的回归，不算新增兼容工作流。
更大的组合仍受预算约束；历史超限证据与较精简公式的既有通过记录继续分别保留。

原始 Python／JavaScript 请求、实现前失败、高精度独立参考和物理 CSV 验证分别保存。
本地数值通过、SDK 序列化通过和 Google 同数据等价分别报告；本批不调用 GEE。
既有三项 S2 binary64 关联／交点往返缺口继续保留，不能用度量容差掩盖。
`distance`、`buffer`、一般投影、无边界完整球面的公共编码及完整生产验收继续待完成。

空 FeatureCollection 的 map 仍只校验回调结构；上述8个方法的必填与未知参数也要验证，
不会为了验证空集合而执行回调。

度量实现见[第七十一批报告](../../reports/gee-python-wave71.json)；
分量传递修复与历史失败见[第七十二批报告](../../reports/gee-python-wave72.json)；
完整重复度量公式修复见[第七十三批报告](../../reports/gee-python-wave73.json)。
