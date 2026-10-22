# 随机森林实现状态与后续接口

2026-10-23 源码与锁定运行库检查：`Classifier.smileRandomForest` 仍未实现。当前已实现的 minimumDistance 以及第二十五批的标签重映射／样本筛选不能代替随机森林。

## 已核对的依据

- [Google 构造器](https://developers.google.com/earth-engine/apidocs/ee-classifier-smilerandomforest) 的参数为树数、每次分裂变量数、最少叶样本、bagFraction、最大叶节点和 seed。其官方示例还使用标签 remap、随机列、样本筛选、模型解释、训练矩阵及独立验证集。当前平台尚不能完整运行该示例。
- 锁定的 Java 21／Spark 4.0.4／Scala 2.13.16 运行库没有 Smile。vendored openEO 的随机森林使用 Spark MLlib，而且存在硬编码深度／bins 和未实现的变量参数；不能将它注册成 Smile API。
- [Smile 4.4.2 LICENSE](https://github.com/haifengl/smile/blob/v4.4.2/LICENSE) 提供 GPLv3／商业许可；[1.5.3 LICENSE](https://github.com/haifengl/smile/blob/v1.5.3/LICENSE) 是 Apache-2.0。版本之间的 API、随机数、依赖和数值实现需要分别核验，不能用旧版本许可描述新版本。
- [Smile RandomForest 源码](https://github.com/haifengl/smile/blob/v4.4.2/core/src/main/java/smile/classification/RandomForest.java) 是后续算法接入依据。Google 没有在上述 API 页披露所用 Smile 版本、完整随机数过程或树训练细节；本地同名算法不自动获得相同 seed／树结构／预测的结论。

## 后续实施路径

1. 固定适合当前 Java 的 Smile 版本、来源、许可证、全部必要依赖和摘要，实际检查 transitive JAR／本地库及线程使用。不自动升级运行库或引入未锁定下载。
2. 新增独立的 RF 模型 IR 和可信 JVM 训练工厂；输入使用真实、有界训练表，GeoTrellis 只负责 tile 分发与预测。保留现有 minimumDistance 实现及其精确模型合同。
3. 明确每个参数的实际行为，特别是 bag 抽样方式、默认 mtry、无上限叶节点、深度、seed／每树随机数和并发。不能静默忽略参数或调用其他 RF 算法替代。
4. 模型只由受控训练工厂构建；不从用户提供的 Java 序列化字节、URL 或路径恢复。dry-run 只提供 schema／traces，模型预测维持波段、时间、掩膜与资源预算。
5. 用真实 Smile 训练／预测加独立 GeoTrellis tile 控制，再接采样、训练、预测、解释及独立验证矩阵。没有 Google 同数据证据时保留相应未知，不将组件探针描述为完整引擎或生产验收。

本次仅完成依赖和接口侦察，没有安装 Smile、改动运行依赖锁或扩大 API 能力声明。标签处理、样本筛选、动态验证结果和随机列是不同的兼容任务，分别记录完成范围。
