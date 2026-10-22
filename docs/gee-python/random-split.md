# `randomColumn` 与训练／验证划分

本页说明第二十九批固定合成工作流。官方 Python SDK 1.7.49 与同版本 JavaScript SDK 都构造 `FeatureCollection.randomColumn` 图；本地编译器只接受已实现的有限参数和表类型。官方 API 的签名、默认值与说明见 [FeatureCollection.randomColumn](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-randomcolumn)。

## 工作流

[Python 示例](../../examples/34_GEE_python_random_split.py)先从固定的合成影像取样，再写入 `split_draw` 随机列。随后先用 `Filter.notNull` 删除类别／输入波段／随机值不完整的行，再按半开区间切分：训练行满足 `split_draw < 0.5`，验证行满足 `split_draw >= 0.5`。两个分支都源于同一随机列，因此没有重叠，且完整覆盖剩余行。Smile 随机森林显式声明 `classProperty`、`inputProperties`、树数、叶大小、采样比例、节点上限和种子。

示例还构造要素分类、验证错误矩阵及全部矩阵访问器、训练重代入矩阵、分类影像、Map 图层、CSV 和 GeoTIFF 导出图。两个采样入口的分类、训练／验证矩阵访问器、Map、CSV 与 GeoTIFF 图都通过离线编译检查。示例不会读取样本行、拟合模型、提交 Map 请求或启动导出。`image_sample_v2` 使用 `Image.sample` 并以生成的 `system:index` 为默认行键；`sample_regions_v1` 保留旧 `Image.sampleRegions` 接口，并显式使用 `cell_id`。

固定原始栅格来自 [Image.sample v1 夹具](../../tests/fixtures/ee-image-sample-rf-v1.json)，split 配置与预期成员清单位于 [random-split v1 夹具](../../tests/fixtures/ee-random-split-v1.json)。独立参考从网格、像元中心和原始 band 数组重新枚举样本，计算行键哈希，再分别统计缺失行、训练／验证成员和类别频数；没有调用生产 randomColumn helper 得出预期值。

## 本地随机值合同

本地 `sha256-rowkeys-v1` 是为离线复现定义的确定性算法。它不是 Earth Engine 的随机数 oracle，不能据此声称同一个种子、要素或 rowKeys 在 Google 上会得到相同随机值或相同划分。`uniform` 从摘要前 53 位生成 `[0,1)` Float64；`normal` 使用两个摘要片段进行 Box–Muller 变换。随机流只由种子和按顺序编码的 row-key 值决定。

编码为带类型标签和长度的二进制帧：字符串按 UTF-8，布尔值单独编码，有限数值按大端 Float64 编码；`-0` 归一化为 `+0`。因此 `true` 与 `1` 不同，键值顺序也会影响结果。输出列名与分布名不参与哈希。默认 `rowKeys` 为 `['system:index']`；有此属性时用属性值，否则用 Feature ID。静态内联表在编译时检查实际键值；采样表先检查声明字段，实际运行再拒绝缺失、null、复合对象或非有限值，不会用行号补造身份。重复的 row-key 值会得到相同随机值。显式空 rowKeys 表示所有行共享同一随机值。

种子支持有符号64位整数，行键数值绝对值最多 `2**53`，字符串最多4096码点；rowKeys 须唯一且不超过64项。输出名须为合法 UTF-8 的非空平面字段，不含 NUL，不能覆盖 `system:index` 或 `.geo`。uniform 与 normal 不保证给出指定数量的训练行；固定阈值形成近似比例。重名覆盖的列按实际 CSV 数值读回，不能从原始采样规格补回旧值。

`randomColumn` 可在采样表操作链中追加，计算仍延迟到受信任运行阶段。覆盖已有列会替换该列值并保留原字段位置；新增列放在 `.geo` 前。Band 顺序元数据仍描述源影像波段，不会因随机列改变。每个表最多 16 个操作、rowKeys 最多 64 项，名称最多 256 个 Unicode 码点；操作规格、编译工作和已有行／列限制继续共同生效。

## 证据边界

`tests/test_ee_random_split_workflow.py` 分别检查固定原始网格和独立 typed-hash 数值参考、Python／JavaScript 官方 SDK 离线图一致性，以及编译器对静态 inline 值和采样表分支的图形输出。SDK parity 提供客户端序列化和本地编译证据；独立参考是本地声明算法的数值 oracle。它不是 Google 同数据对照，也不表示完整 Spark、批任务、沙箱、HTTP、浏览器或部署验收。真实 JVM／原生组件结果由单独的 `tests/test_ee_random_split_native_integration.py` 探针记录，和这里的编译／oracle 证据分开。

第二十九批完整回归为2600通过／3跳过，另排除4项延期原生运行测试。独立原生夹具 `ee-random-split-native-v1.json` 的实际GeoTrellis取样内核返回32行；真实Python表操作按独立哈希参考分为16行训练、16行验证，再经带认证的回环Py4J进入实际Smile工厂。验证矩阵为 `[[7,0],[0,9]]`，训练重代入矩阵为 `[[9,0],[0,7]]`，分别与实际预测的独立频数统计一致。这是固定合成组件的结果，不估计科研项目精度，也不是独立重写随机森林算法的对照。
