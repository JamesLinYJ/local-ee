# Smile 随机森林要素验证

分类表同时保留 JSON 读取与 CSV 导出的合同。即使只调用 `getInfo()`，输入和输出仍须满足既有表格／CSV 大小与结构限制，以及 JSON 公开值的物化预算；小于 1 MB 并不保证含大型嵌套属性的表能够执行。训练、预测和指标步骤各自计量对象与 wire 工作，原有编译、表操作和任务限额继续生效。

示例 32 将固定 Smile 1.5.3 随机森林用于要素训练与验证。它保留两个独立训练入口：内联 `FeatureCollection`，以及从固定训练影像 `sampleRegions` 后执行 `notNull`、筛选和 `limit` 的样本表。两条路径都调用 `FeatureCollection.classify` 生成要素预测；分类器的 `confusionMatrix()` 是训练样本上的重代入矩阵，验证矩阵则由独立验证要素的真实类别和预测类别生成。Google 将 `FeatureCollection.classify` 定义为给要素集合分类，且每个要素需要包含分类器的输入属性；分类器矩阵报告训练数据上的输入类别与输出类别；`FeatureCollection.errorMatrix` 以实际类别为行、预测类别为列，并允许用 `order` 指定轴的类别顺序。[FeatureCollection.classify](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-classify)、[Classifier.confusionMatrix](https://developers.google.com/earth-engine/apidocs/ee-classifier-confusionmatrix)、[FeatureCollection.errorMatrix](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-errormatrix)。

```python
workflow = build_workflow(ee, fixture, training_mode="sampled")
predicted = workflow["validation_predictions"]
training_predicted = workflow["training_predictions"]
matrix = workflow["validation_matrix"]

# 每项都是从本地运行时图直接读取的有界 getInfo 结果。
matrix_values = workflow["validation_values"]
accuracy = matrix_values["accuracy"].getInfo()
class_order = matrix_values["order"].getInfo()
predicted_features = predicted.getInfo()

# 启动本地 CSV 任务，并在工作台中保存任务结果。
result = run_local(ee, workflow, fixture, "sampled")
```

完整工作流见 `examples/32_GEE_python_rf_validation.py`。训练要素集合和留出验证要素集合都会分类，训练分类器的重代入矩阵则单独提供。`run_local()` 通过本地 `getInfo` 路径读取各个矩阵访问器和有界的验证分类要素集合，然后用显式选择器启动 `ee.batch.Export.table.toDrive`。本地适配器将结果写入本地文件；`toDrive` 不会向 Google Drive 上传数据。示例默认的 `main()` 只编译图，不代表已完成随机森林拟合。实际拟合和预测由可信的 Smile 运行时进程执行。

测试夹具的样本源是固定的 3×6 合成网格，并声明了比例尺。`sampleRegions` 的网格和数据源不受留出验证要素或目标地图／导出选项影响。留出表会保留要素 ID、点几何和原始属性，并在几何列前插入 `rf_prediction`。该表的属性插入顺序是 `nir` 在 `red` 前，而模型 schema 明确为 `["red", "nir"]`；运行时模型必须按声明的 schema 顺序读取输入。

测试通过 `Counter` 独立统计原始真实类别／预测类别对，并使用 `fractions.Fraction` 计算准确率、kappa、逐类消费者／生产者准确率和 F-score。参考数据覆盖非对称三分类矩阵、显式排序中的负类别、缺失／null 行、超出声明顺序的完整行、带显式顺序的空矩阵，以及零分母情形。原始类别对控制用于验证矩阵汇总和指标约定，不能替代 Smile 模型预测证据。

已知为空的内联集合 `FeatureCollection([])` 可以调用 `classify` 并编译；结果保留 0 行，不伪造预测，同时声明 `system:index`、预测属性和 `.geo` 列。对该空结果调用 `errorMatrix` 时必须显式提供 `order`，以确定空矩阵的类别轴；省略顺序会在编译阶段失败。显式顺序只定义矩阵形状和标签，不会填充计数。空矩阵上的准确率、kappa、消费者／生产者准确率或 F-score 若遇到零分母，会在运行时失败，不返回 null、NaN 或伪造的零值。测试中的 `None` 仅表示独立有理数参考将该指标标记为未定义，不表示运行时返回 JSON null。

当前仅支持把分类要素表直接读取、导出，或直接传入 `errorMatrix`。分类后继续执行 `filter` 等要素表操作不在支持范围内；运行时表、矩阵和指标值也不能参与一般算术或装入通用动态结果容器。训练混淆矩阵是重代入矩阵，不是袋外准确率。`randomColumn`、其他分类器和模式、持久化／explain、完整 Spark 作业行为、浏览器交互、Google 服务对照和部署验收均不属于本批范围。Python／JavaScript SDK 的语义序列化一致，只能说明客户端请求含义一致，不能证明随机森林已经拟合。

运行以下聚焦检查：

```bash
.venv/bin/python -m pytest -q tests/test_ee_rf_validation_workflow.py
```

这些测试只编译图并检查运行时进程连接，不会调用 Google 或启动应用服务。实际引擎执行需要由可信 JVM／运行时测试及其报告另行证明；编译测试本身不构成端到端数值验收。
