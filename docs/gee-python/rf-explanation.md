# 随机森林解释结果

`Classifier.explain()` 支持本地已训练的 Smile1.5.3 随机森林。Python 与 JavaScript 均使用固定官方客户端构图；编译时不拟合模型，实际诊断值由可信 JVM 中的同一个模型返回。

```python
model = ee.Classifier.smileRandomForest(50).train(
    features=training, classProperty='label', inputProperties=['red', 'nir'])
explanation = model.explain()
print(explanation.getInfo())
importance = ee.Dictionary(explanation.get('importance'))
print(importance.get('nir').getInfo())
print(importance.values(['nir', 'red', 'nir']).getInfo())
print(explanation.get('numberOfTrees').getInfo())
```

JavaScript 同样可调用 `model.explain()` 和 `ee.Dictionary(...).get(...)`，由工作台 `print` 读取支持的结果。完整离线构图示例见 [示例37](../../examples/37_GEE_python_rf_explanation.py)。运行计算需要已有的固定 RF 运行包；源码与独立组件验证不表示已更新本机部署。

| 字段 | 实际含义 |
| --- | --- |
| `importance` | 训练 schema 中每个字段的实际树分裂 Gini 减少量之和；没有归一化为百分比 |
| `numberOfTrees` | 模型实际树数量，并与训练参数复核 |
| `outOfBagErrorEstimate` | Smile1.5.3 原始袋外错误率；不等于独立验证集准确率 |

袋外错误沿用固定 Smile 版本的策略：若没有获得任何袋外投票，该库也可能返回0。不得据此宣称模型完美，仍应使用独立留出集和验证矩阵。Google 的模型版本、树、随机序列、字段格式与数值均未作同数据对照；`trees` 文本不提供。

解释对象保持独立运行时类型，支持字典 `get/keys/contains/values` 及匹配类型的 `Dictionary/Number/List` 转换。`keys` 按键排序；`values` 省略 keys 时使用该顺序，显式 keys 最多64项，保留顺序和重复。缺键只有提供非 null 默认值时返回默认值。键名与是否包含键可根据已声明结构静态读取，重要性／误差／树数量从实际模型读取。

解释值只可作为直接 JSON/getInfo 结果，不能嵌入一般容器、Feature 属性或计算图回调，不支持通用动态数学、修改字典或 CSV／栅格导出。未训练模型、其他分类器、额外字段及未列明操作明确拒绝。训练来源仍受既有 schema、行数、树数、RF150000对象工作与3MB扫描、表50000工作及JSON1MB等界限约束；手写进程图也需通过生产者、schema和树数量校验。

这里的回调限制针对后端 openEO 运行时回调。有限 EE 静态控制流可以选出同一个直接最终解释结果，例如静态 `If` 或内联集合 `iterate`；输出仍是绑定原训练器的同一类型化 JSON 图，不能借此把解释对象传入其他运算或容器。

编译器仍按原有50000工作预算重新校验模型的规范训练规格；explain及每次投影读取都会增加开销。因此即使训练行数没有超过1000，较大的内联训练表或复杂读取链也可能明确超限，不能把行数、字段数、键数的各自上限组合成保证容量。本批保留该保护，未通过提高预算放行。

结果沿用现有任务、父脚本／用户权限和物理文件边界。worker 发布前和 API 读回时按可信任务规格复核形状，拒绝重复键、非有限值、超深／超大结构、非物理文件与错误结果类型。旧矩阵结果仍只接受其原有数值合同。dry-run 不拟造重要性、树数量或袋外统计。

版本化合成夹具 `ee-rf-explanation-v1.json` 使用8行、一个常量字段和一个可完全分离字段，3棵最多2叶的树，每棵根节点 Gini 为1/2、子节点为0。独立参考因此为常量重要性0、信号重要性3/2、树数量3、袋外错误0；实际 JVM 结果与此比较，另经真实JSON写出和任务读回。它验证这个可手算样本，不代表所有森林的重要性、真实遥感预测能力或 Google 数值等价。

官方接口定义见 [Earth Engine Classifier.explain](https://developers.google.com/earth-engine/apidocs/ee-classifier-explain)，实际统计来源见 [固定 Smile1.5.3 RandomForest](https://github.com/haifengl/smile/blob/v1.5.3/core/src/main/java/smile/classification/RandomForest.java)。
