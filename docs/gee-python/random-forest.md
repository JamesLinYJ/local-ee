# Smile 随机森林语法与本地执行合同

本地实现使用固定的 **Smile 1.5.3 RandomForest（Apache-2.0）**，不是 Spark
MLlib。Google 的参考页没有公开其服务端 Smile 版本、抽样和种子细节；同名
API、同一个 seed 不构成相同树结构或 Google 数值结果的保证。

## Python 与 JavaScript

Python 使用已配置的官方 `ee` 客户端。下面显式列出预测字段；第三十批也支持从已声明 `band_order` 读取省略的字段，见 [训练字段](training-schema.md)：

```python
model = ee.Classifier.smileRandomForest(
    numberOfTrees=100,
    variablesPerSplit=None,
    minLeafPopulation=1,
    bagFraction=0.5,
    maxNodes=None,
    seed=42,
).train(
    features=training,
    classProperty="label",
    inputProperties=["red", "nir"],
)
classified = image.classify(model, "landcover")
```

JavaScript 的同一调用可写为：

```javascript
var model = ee.Classifier.smileRandomForest({
  numberOfTrees: 100, variablesPerSplit: null, minLeafPopulation: 1,
  bagFraction: 0.5, maxNodes: null, seed: 42
}).train({features: training, classProperty: 'label',
          inputProperties: ['red', 'nir']});
var classified = image.classify(model, 'landcover');
```

`training` 可以是本地内联 FeatureCollection，也可以是已有的
`image.sampleRegions(...)` 结果及其 `filter(...)`／无排序 `limit(...)` 链。
训练数据只在批任务中交给 JVM；API 编译过程不拟合模型。版本化合成示例见
[示例 31](../../examples/31_GEE_python_smile_random_forest.py)。示例的地图和导出
表达式可编译，CLI 的 `submitted:false` 表示没有提交实际地图／导出任务。

## 参数与数据

| 参数 | 支持范围与实际行为 |
| --- | --- |
| `numberOfTrees` | 必填，整数 1–256 |
| `variablesPerSplit` | `None`／`null` 为 `floor(sqrt(p))`；显式整数 1–p |
| `minLeafPopulation` | 整数 1–1000，传给 Smile `nodeSize` |
| `bagFraction` | 有限数值 `(0,1]`；Smile 1.5.3 按类分层抽样，等于 1 时有放回，小于 1 时不放回且按类计数四舍五入 |
| `maxNodes` | `None`／`null` 用训练行数 N 作为非额外限制的上界；显式整数 2–1000，不偷偷使用库默认的 100 叶上限 |
| `seed` | 有符号 32 位整数；同一 JVM 调用线程设种，串行训练，拒绝已初始化为多线程的 Smile 执行器 |

输入字段为 1–8 个唯一的平面属性名，训练行数为 2–1000；类别标签为从 0 连续
编号的 2–64 类整数。缺值、布尔或非有限训练数值明确失败，不自动删除训练行；
需要时先用 `Filter.notNull` 筛选。整数绝对值不超过 `2^53`；训练浮点绝对值
不超过 `Double.MAX_VALUE/2`，避免该版本树分裂阈值 `(a+b)/2` 的加法溢出。
预测读取实际 Float32／Float64 值，不提前降为 Float32。

`train` 的 `subsampling=1`、`subsamplingSeed=0`；其他值目前拒绝。训练表的
schema 顺序保留；目标影像按字段名提取并重排，额外波段不影响有效性。选中波段
有 NoData 时输出掩膜，有限输入保留原精度，实际 Infinity 拒绝。输出是本地
Int32 NoData 波段，默认名称 `classification` 或显式 `outputName`，保留目标的
属性、网格、时间和足迹。Google dtype 和投票平分规则的等价性未验证。

## 模型、预算与运行包

内联行生成 `local_ee_train_smile_rf_rows`；采样行生成
`local_ee_train_smile_rf_samples`；两者的受控模型只允许进入
经审查的栅格／要素预测或训练重代入矩阵消费者。模型不能藏进其他参数容器或 `save_result`，
也不接受用户提供的 Java 序列化、URL 或模型路径。回调引用保留独立作用域；
规范 JSON 字符串中的属性名不会变成流程引用。

采样训练使用独立的固定来源／网格子图；目标地图或导出的 `region`、`scale`
不改变训练样本。dry-run 只保留 schema 和来源 traces，不生成训练行、模型或
预测结果。实际预测拒绝 pending 模型以及其他分类器类型。

预算同时成立，行数上限不代表任意字段宽度均能执行：

- 原有 500 节点、编译工作 50000、采样行／列／1 MB／网格和解码限制不变。
- 原采样表操作仍最多 16 次、累计工作 50000；RF 验证该计数后纳入自身最多
  150000 的对象／复制／操作工作。复制包含未选元数据的完整结构，先计费后复制。
- RF 独立累计 wire 扫描／编码预算为 3 MB；每个 JSON 仍最多 1 MB，模型规格
  最多 16384 UTF-8 字节。此计量把字符串字节与对象复制区分开。
- 训练 `N × 树数 × p × min(N,有效叶上限) ≤ 10^9`；预测使用真实可信模型的
  `sum(DecisionTree.maxDepth()) × 网格像元 × key数 ≤ 10^9` 节点访问上界。
- 任务的 CPU 时间、RSS、进程和文件／网络沙箱约束继续生效。

独立构建脚本 `scripts/build_smile_rf_adapter.py` 和
`deploy/smile-rf-lock.json` 固定 RF SPI、四个 Smile JAR 与复用的 Spark SLF4J。
只接收显式本地依赖目录，构建／运行校验摘要；运行时不下载。部分安装、摘要
错误、重复 SLF4J 或未锁定 classpath 项会在创建 SparkContext 前失败。
本批不修改 `.native`、不部署或重启服务；当前已有运行环境不会自动获得 RF。

## 尚未支持与证据范围

第二十七批补充了有界 `FeatureCollection.classify`、真实训练重代入矩阵及
验证表 `errorMatrix` 的七种指标访问器，结果通过原有任务的 JSON／CSV 边界
返回；具体参数、空表及预算见 [要素验证语法](rf-validation.md)。模型也可进入
受控的要素预测／训练矩阵节点，不能进入通用运算或直接输出。

RF 的 `explain`、其他输出模式和模型保存／恢复
尚未实现；Image.sample 与随机列已有各自有限合同。`schema()` 和
`setOutputMode('CLASSIFICATION')` 支持，其他模式明确拒绝。

第三十批支持省略或null的 `inputProperties`，仅从内联集合或Image.sample v2实际声明的 `band_order` 读取完整顺序；显式列表优先，不猜字段或自动删除类别。固定Python SDK会丢弃GeoJSON集合根properties，应使用实际 `.set('band_order',...)` 调用。sampleRegions v1仍需显式字段；完整限制见 [训练字段与集合元数据](training-schema.md)。

官方 SDK S／编译 C、可信独立 JVM／GeoTrellis tile 组件和原始合成参考分别记录。
它们不能代替完整 Spark／批处理沙箱／HTTP／浏览器、私有真实数据、部署或 Google
同数据验收。实测汇总由本批报告列出。

依据：[Google RF 构造器](https://developers.google.com/earth-engine/apidocs/ee-classifier-smilerandomforest)、
[Smile 1.5.3 源码](https://github.com/haifengl/smile/tree/v1.5.3)、
[该版本许可证](https://github.com/haifengl/smile/blob/v1.5.3/LICENSE)。
