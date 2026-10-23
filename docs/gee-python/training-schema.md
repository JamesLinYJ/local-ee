# 训练字段与集合元数据

官方 [`Classifier.train`](https://developers.google.com/earth-engine/apidocs/ee-classifier-train) 将 `inputProperties` 定义为可选参数：训练集合包含 `band_order` 时可省略。第三十批为本地 minimumDistance 和 Smile RandomForest 接通这一规则，继续使用原有明确字段的引擎训练规格，未新增 Java 算法或改变模型训练方式。

## 字段选择

```python
# training 为已有内联训练表，label 是独立类别属性。
training = training.set('band_order', ['nir', 'red'])
model = ee.Classifier.smileRandomForest(50).train(
    features=training,
    classProperty='label',
)
print(model.schema().getInfo())  # ['nir', 'red']
```

省略 `inputProperties` 或传入 `None`／JavaScript `null`，都采用集合实际声明的完整 `band_order`。有值的显式列表优先；`[]` 是非法空字段列表，不触发自动选择。没有元数据、值为 null、字段重复或不是合规列表时明确失败，不从第一行、属性键或所有数值字段推测输入。

顺序与内容按声明保留。若 `classProperty` 本身在 `band_order` 中，本地不会擅自删除它。`Image.sample` 会声明所有选中波段，包含以波段形式加入的类别；需要排除类别或辅助波段时，应显式使用 `inputProperties=['nir','red']`。同一个声明产生的自动与显式训练规格、编译图已经分别对照；未运行 Google 同数据对照，不能据此声称所有 Google 默认行为相同。

自动字段限1–8个唯一、非空的平面 UTF-8 名称，每项最多256码点，无点号或NUL，不能为 `system:index`、`.geo`。类别、数值、行数、模型和共同工作预算沿用各分类器的现有限制，自动字段不扩大算法支持范围。

## 取样集合

`Image.sample()` 的 `band_order` 来自经过验证的来源规格，读取元数据不会读取或构造样本行。经过已支持的 `randomColumn`、`filter`、`limit` 后，自动字段仍取源波段顺序；新增随机列不会自动成为输入。覆盖原有字段后，训练使用该字段实际变换后的数值。

```python
samples = image.sample(region=roi, seed=42, dropNulls=True)
print(samples.get('band_order').getInfo())
# 仅在确实需要该完整列表时省略 inputProperties。
model = ee.Classifier.minimumDistance().train(samples, 'label')
```

旧 `sampleRegions` v1 输出尚未声明集合级 `band_order`，继续要求显式输入。动态取样集合的 `.set()`／`.setMulti()`／`.copyProperties()` 尚未接通；它们明确拒绝，不伪造来源元数据。

## 内联集合元数据

有限内联 FeatureCollection 支持集合级 `get`、`set`、`setMulti`、`propertyNames` 及集合之间 `copyProperties`。元数据在根 `properties`，与每行 Feature 的 `properties` 分开；调用不会把同名字段写入各行。输入与返回值保持独立副本，修改返回列表或嵌套字典不会污染原集合。

筛选、排序或无排序 `limit`、`randomColumn`、map到Feature及静态最小距离分类保留集合元数据，空结果也保留。map到Image仍返回ImageSequence；merge沿用现有行为，不提供元数据冲突合并规则，需要时在合并后明确设置。`copyProperties` 的 source／destination 目前须同时为内联集合，混合 Image／Feature 或动态取样不支持。

固定 Python SDK 的 GeoJSON FeatureCollection 构造器会舍弃输入集合根元数据。应使用 `.set('band_order', ...)`，它会序列化为实际 Element 调用；不能只把 `properties` 填在传给构造器的 GeoJSON 上。

元数据只接受有限 JSON；共享50000编译工作预算、深度96、每层最多10000个元数据属性、1 MB转义JSON及既有公开结果限制共同生效。扫描与复制各自计费，组合操作可在较小数据量时达到预算。`process_id`、`from_node`、`process_graph` 等元数据名和值保持普通数据，不能进入计算图依赖或执行路径。

## 复现与证据

[示例35](../../examples/35_GEE_python_training_schema.py) 使用版本化有限夹具，分别构造内联集合和实际Image.sample的自动训练字段图。命令行只做离线编译，不拟合RF、不提交任务或导出。

`test_ee_training_metadata_workflow.py` 用独立原始均值／距离核对内联最小距离预测，检查Python／JS官方客户端编译一致性，并通过真实受限CSV写出函数验证集合元数据始终为字面值。`test_ee_random_split_native_integration.py` 在启动JVM前从官方客户端省略参数的表达式推导RF规格，与显式完整列表对照后，将该规格交给真实取样表／随机划分／Smile训练与预测组件。

这些证据分别是S／C、局部独立数值参考和可信Python／JVM组件。完整Spark／RDD适配、批任务沙箱、HTTP／浏览器、部署、私有数据及Google同数据验收另行记录；不把局部通过当作整体兼容。最终回归与范围见 [第三十批报告](../../reports/gee-python-wave30.json)。
