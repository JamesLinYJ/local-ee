# 分类后的要素表操作

`FeatureCollection.classify()` 的有限本地 Smile RF 结果可以继续调用
`filter`、无排序的 `limit` 和 `randomColumn`，再调用 `errorMatrix`、
`getInfo()` 或 CSV 导出。静态 minimumDistance 的内联表继续沿用原有路径。
官方 [classify 示例](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-classify)
也采用先分类、后筛选验证集的顺序；本地实现范围仍以本页为准。

```python
split = samples.randomColumn('split', 29)
training = split.filter(ee.Filter.lt('split', 0.5))
model = ee.Classifier.smileRandomForest(13, seed=41).train(
    training, 'landcover', ['reflectance'])
predictions = split.classify(model, 'prediction')
validation = predictions.filter(ee.Filter.gte('split', 0.5))
annotated = validation.randomColumn('audit_draw', 31)
limited = annotated.limit(8)
print(limited.errorMatrix('landcover', 'prediction', [0, 1]).array().getInfo())
task = ee.batch.Export.table.toDrive(collection=limited, fileFormat='CSV')
task.start()  # 创建本地任务，下载目的地仍是本工作台
```

显式训练字段排除类别字段。若选择自动 `band_order`，列表中的类别也会作为输入，
不能据此报告验证准确率。上述固定合成数据只验证接口和计数，不证明研究数据上的预测能力。

编译阶段保留分类器和原始取样分支，按顺序附加独立的表操作，不在 API 进程拟合或预测。
运行时只接受实际分类表或同一次 dry-run 的待执行分类表；待执行对象只有列和来源，
没有虚构的样本行。新增随机列插入 `.geo` 前，覆盖普通字段保留原列位置；行标识、
几何、集合元数据和列顺序保留，输入表不被修改。`rowKeys` 按当前步骤的列校验，
实际缺失或 null 行键会失败。默认随机键须有真实 `system:index` 或 Feature ID，
不会按行号补造。随机值使用已说明的本地算法，不保证与 Google 相同。

取样前置操作与分类后操作合计最多16步。表操作累计50000工作预算、1000行、256列、
50000单元、1MB JSON/CSV 和既有图规模限制继续生效，允许的形状也可能因共同预算失败。
RF 拟合与预测保留单独的既有预算。`limit(0)` 保留空表和列；空矩阵须显式给类别顺序，
未定义的准确率等指标报错。一般 map、排序、merge、再次训练、动态通用算术、
未实现分类器/模式仍明确拒绝。

[示例36](../../examples/36_GEE_python_classified_tables.py) 可离线编译；对应测试分别记录
Python/JS 官方客户端图一致性、实际可信 JVM 预测后的表操作和矩阵计数，以及物理
JSON/CSV 写出与读取。这些证据不等于完整 Spark 作业、HTTP/浏览器、部署或 Google
同数据验收。当前批次证据见 [Wave31报告](../../reports/gee-python-wave31.json)。
