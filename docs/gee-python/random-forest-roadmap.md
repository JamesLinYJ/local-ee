# 随机森林实现状态与后续接口

2026-10-23 第二十六批新增有限 `Classifier.smileRandomForest` 实现：真实 Smile1.5.3、内联／采样表运行时训练、影像分类、schema 与 CLASSIFICATION 模式。语法、参数、预算、独立运行包和验收边界见 [RF 文档](random-forest.md)。minimumDistance、Spark MLlib 与本实现属于不同算法，不能互相冒充。

## 已核对的依据

- [Google 构造器](https://developers.google.com/earth-engine/apidocs/ee-classifier-smilerandomforest) 的参数为树数、每次分裂变量数、最少叶样本、bagFraction、最大叶节点和 seed。其官方示例还使用标签 remap、随机列、样本筛选、模型解释、训练矩阵及独立验证集。当前平台尚不能完整运行该示例。
- 原有 Java 21／Spark 4.0.4／Scala 2.13.16 运行库没有 Smile。本批的独立构建锁固定四个 Smile1.5.3 JAR 及复用的 Spark SLF4J，不改现有 `.native` 或上游 engine-lock。vendored openEO 的 Spark MLlib 实现未注册为 Smile API。
- [Smile 4.4.2 LICENSE](https://github.com/haifengl/smile/blob/v4.4.2/LICENSE) 提供 GPLv3／商业许可；[1.5.3 LICENSE](https://github.com/haifengl/smile/blob/v1.5.3/LICENSE) 是 Apache-2.0。版本之间的 API、随机数、依赖和数值实现需要分别核验，不能用旧版本许可描述新版本。
- [Smile RandomForest 源码](https://github.com/haifengl/smile/blob/v4.4.2/core/src/main/java/smile/classification/RandomForest.java) 是后续算法接入依据。Google 没有在上述 API 页披露所用 Smile 版本、完整随机数过程或树训练细节；本地同名算法不自动获得相同 seed／树结构／预测的结论。

## 已落实的接口

1. 固定版本、Maven 来源、Apache-2.0、四个 JAR 的摘要、唯一 SLF4J、构建与源码 manifest；独立 RF SPI，不自动升级或运行时下载。
2. 独立 RF IR 与 JVM 工厂，API 只编译；保留 minimumDistance 的精确模型合同和采样 CSV 封闭图。
3. 六参数实际传递；mtry 默认 floor sqrt，maxNodes=null 使用非约束的 N，按类 bag 抽样，调用线程串行设种，并读取线程池状态失败关闭。
4. 只接受工厂的 opaque 模型，dry-run 无假模型／预测；限制来源、schema、掩膜、训练／预测工作与整个模型消费路径。
5. 真实 Smile／GeoTrellis tile 组件探针与原始合成参考分开记录；没有完整 Spark／沙箱／浏览器或 Google 对照结论。

## 剩余工作

官方完整分类示例还依赖随机列、RF explain、训练／验证混淆矩阵、表分类和数据集镜像，目前尚不能整段运行；其他输出模式、模型保存／恢复、Image.sample 与 band_order 自动 schema 也未实现。后续应建立真实动态表结果协议再补这些能力，保留实际 Smile 版本／抽样与 Google 细节未知的边界。本批只构建和验证独立运行包，没有安装到 `.native` 或部署。
