# 原生加权邻域统计

内部 GeoTrellis SPI `local_ee_neighborhood` 对单波段 Float64 数据立方体的实际像元执行邻域统计。它接收唯一的 `spec` 字符串参数，输出单个 `v` 波段和 NaN NoData，并保留已有空间键、SpaceTimeKey 时间、网格与立方体元数据。

规格是最多 32768 字节的 ASCII 紧凑 JSON，字段按键名排序，且必须逐字节符合规范编码：

```json
{"coefficients":[[-1,0,"3ff0000000000000"],[0,0,"4000000000000000"],[1,0,"3ff0000000000000"]],"operation":"mean","skip_masked":true,"v":1}
```

`coefficients` 是 1–1089 个 `[dx, dy, weightBits]` 三元组，偏移范围为 -32 到 32，按 `(dy, dx)` 排序且不重复。权重是小写 16 位 IEEE-754 binary64 原始位，必须为严格正的有限数；零权重应由编译器省略，空权重集合拒绝。Scala 会独立验证 JSON 字段、重复键、类型、范围、顺序、规范编码和权重规则。

支持 `sum`、`mean`、`count`、`min`、`max`、`variance`、`stdDev`、`sampleVariance`、`sampleStdDev`、`product`、`median` 和 `mode`。`sum` 保留权重规模，不除以权重总和；`mean` 使用实际有效邻值对应的权重总和。`variance` 与 `stdDev` 是按系数加权的总体统计。`count`、`min` 和 `max` 忽略权重大小；`sampleVariance`、`sampleStdDev`、`product`、`median` 和 `mode` 要求每个权重都恰为 1。少于两个有效邻值时，样本方差与样本标准差输出 NoData；mode 同频时选数值最小项。

窗口只读取边界内、存在的源 tile 中的有效像元。缺失 tile、栅格边缘或掩膜邻值不会使整窗失效，它们从统计中省略；零有效支持统一输出 NoData，包括 `count`。`skip_masked=true` 保留掩膜中心，false 只会在已存在的中心 tile 内填充像元。算子不会创建缺失的空间键或时间键；SpaceTimeKey 邻值只来自同一时间。

数值内核把每个输入和权重分解为二进制有效数与指数。`sum`、`mean` 和矩使用预先选定的公共指数，用小的有效数乘积移位后精确累积；这避免先形成可能溢出的浮点乘积，也保留大公共偏移下的微小方差。加权方差由精确有理矩 `Q·W - S²` 计算，再一次性舍入到 binary64；标准差对同一有理数执行整数平方根，并以精确中点比较决定最近偶数结果，不使用近似容差或无界修正循环。平方根先对精确整数商求向下取整的整数根，随后中点比较至多将根加一，因此舍入修正最多一步。`product` 也累积精确有效数和指数，最后一次舍入；任何最终有限 Float64 溢出都会明确失败。

适配器复用共享栅格键、时间、尺寸、NoData、有限输入与单波段检查。创建 halo 前会验证源键和 tile；半径零直接处理原 tile，正半径必须小于 tile 较短边。空间与时间 collection buffer 只返回原有键。

预算保持现有上限：100000 个源键、100000000 个总解码单元、10000000 个 tile 单元、每 tile 100000000 和总计 1000000000 个工作单位。工作估算覆盖每邻值有效数乘法和移位、W/S/Q 精确累积、平方有效数的两次小乘法、矩与分母乘法、舍入时分母移位与线性 limb 扫描，以及标准差的有界整数开方和精确中点比较。实际读回显示：单位权重 3×3 mean 在 256×256 下为 64291844 单位并通过；7×7 mean 为 260901924，超过每 tile 上限而拒绝。3×3 exact variance 在 256×256 下为 243270660 并拒绝，在 128×128 下为 60817924 并通过；对应 3×3 stdDev 和 sampleStdDev 分别估算为 300155908 与 300221444，均超过 256×256 每 tile 上限。两种 stdDev 的探针断言还分别核对了它们比相同支持的方差统计多计平方根工作。没有提高任何预算上限。

`tests/test_ee_neighborhood_kernel.py` 的 opt-in JVM 探针通过已锁定 JDK、Scala、GeoTrellis 和 Spark 依赖构建现有独立 adapter JAR，但不启动 SparkContext。19 个合成用例的 456 个像元同时经过手动 halo 与 `BufferTilesRDD` collection buffer，并与独立 Python `Fraction`／高精度 `Decimal` 全栅格参考逐位比较。覆盖全部算子、舍入与中间溢出边界、大公共偏移、极小／极大权重、掩膜、缺失 tile、空支持、半径零、时间隔离、严格 wire 和预算拒绝。日志、输入、manifest 和结果保存在 `audit/gee-python-wave44/native/`。

本探针证明独立 GeoTrellis tile kernel 和 collection buffer 的合成数值行为；它没有运行完整 Spark RDD 作业、原生任务沙箱、服务、浏览器、部署或私有真实数据，也没有 Google 同数据数值对照。原生部署与真实数据验收仍按当前阶段要求延期。
