# 影像取样与运行时分类

本页记录第二十四批有限 `Image.sampleRegions` 合同。官方 Python／JS SDK 序列化、编译图、独立合成数值、真实 GeoTrellis tile 内核和可信任务／CSV 控制分别验证；完整 Spark cube、隔离任务、浏览器、部署、真实影像和 Google 同数据验收未运行。当前运行服务不因源码更新自动获得这些能力。

## Python 写法

```python
import ee

image = ee.Image('本地已入库场景ID').select(['red', 'nir'])
regions = ee.FeatureCollection([
    ee.Feature(ee.Geometry.Point([113.5, 22.3]), {'landcover': 0}),
    ee.Feature(ee.Geometry.Point([113.6, 22.4]), {'landcover': 1}),
])
samples = image.sampleRegions(
    collection=regions, properties=['landcover'], geometries=True,
)
model = ee.Classifier.minimumDistance('euclidean').train(
    features=samples, classProperty='landcover',
    inputProperties=['red', 'nir'],
)
classified = image.classify(model)
Map.addLayer(classified, {'min': 0, 'max': 1}, '类别')

# 获取样本会提交本地异步取样任务，客户端等待结果；不会在编译时伪造像素。
print(samples.getInfo())
task = ee.batch.Export.table.toDrive(
    collection=samples, description='训练样本', fileFormat='CSV',
    selectors=['system:index', 'landcover', 'red', 'nir', '.geo'],
)
task.start()
```

场景、坐标和训练标签需要换为自己的有效本地数据。这是使用写法，完整版本化合成工作流见 [示例 29](../../examples/29_GEE_python_sample_training.py)，可以仅编译而不提交任务。

## 网格、掩膜与属性

- 单张空间影像，1..64 个唯一标量波段；可先选择、计算或重命名波段。所选任一波段为 NoData 时不生成该行，实际有效 Infinity 明确拒绝。
- 支持内联、非空、有效二维平面 WGS84 的 Point、MultiPoint、Polygon、MultiPolygon。点按实际网格 floor 归属像元，东／南外边界不在网格内；多点在同一要素内按像元去重。多边形选取正面积相交的像元，单纯边界接触不计入。不同要素重叠会保留多行及相应训练权重。这是明确的本地政策，尚无 GEE 球面或边界等价结论。
- `properties` 默认复制非 `system:` 属性；显式 `[]` 不复制。缺少的已选属性记为 null。属性与波段或保留列重名时拒绝。`geometries=True` 输出像元中心点，默认不输出几何。
- 省略 `scale`／`projection` 保留原生网格。显式 `scale` 为正的有限米制尺度；可以同时指定受支持的投影 EPSG。实际 CRS 必须为米制投影，两轴实际像元宽高与声明尺度按相对 `1e-9` 核对；缺少布局、尺度不符、地理或英尺网格拒绝。单独 projection、tileScale≠1 尚未支持。
- 分类目标的 map、导出 region／scale 不会改变固定训练场景及其取样网格。输出像元预算只追踪分类目标；训练输入另做预算，并保留原生 tile／key／decoded-cell 限制。

## 范围与限制

最多 1000 个区域、10000 个坐标位置；输出最多 1000 行、含保留列的 256 列、50000 行列单元和各 1 MB JSON／CSV。达到边界时整体失败，不截断样本。共享 50000 编译工作、500 图节点及表达式字节上限继续生效；原生候选 tile 像元×区域工作还限制在 67108864。

取样表可以 `getInfo()`、导出 CSV，或直接训练有限 minimumDistance：Euclidean、Manhattan、cosine，k=1／CLASSIFICATION，显式 1..8 个输入属性，整数类别 0..63，subsampling=1／seed=0。真实样本按 binary64 精确有理数计算类均值，并向分类内核传递精确模型。等距和 cosine 零范数仍按已有合同拒绝。

动态取样表的通用 map／filter／reduceColumns、动态模型的 FeatureCollection.classify／confusionMatrix、自动 schema、随机取样、其余分类器／模式、其他矢量格式和云导出目标尚未实现。不能将方法可见、模型 schema、编译成功或单独内核验证视为完整计算验收。

## 协议与结果边界

`local_ee_sample_regions → local_ee_train_minimum_distance → local_ee_minimum_distance` 保留独立栅格／表格／模型类型。采样与训练规格是规范 JSON 字符串，内部的 `process_id`、`from_node` 等属性仍是数据。模型引用只能直接来自审核过的训练节点；其他来源拒绝。

dry-run 表和模型只保留 schema 与源 traces，不生成假行／类中心。样本表使用上游 `save_result` 合同写入本任务物理目录，CSV 使用独占、不跟随链接的创建方式。结果读取复核任务所有权、脚本父任务、列、行 ID、原属性、有限像素值及大小。空样本返回空 FeatureCollection／只有表头的 CSV；空表训练明确失败。

详细证据与已修复问题见 [第二十四批报告](../../reports/gee-python-wave24.json)。
