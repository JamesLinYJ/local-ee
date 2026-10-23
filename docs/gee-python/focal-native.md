# 有界原生 focal 计算

`local_ee_focal` 是内部 GeoTrellis SPI，输入为一个单波段数据立方体和唯一的 `spec` 字符串参数。Scala 端会独立解析规格、再次检查输入，并在实际 Float64 像元上执行邻域归约。输出使用 NaN NoData 和单个 `v` 波段，沿用源空间键、观测时间键和立方体元数据；编译器可以在外层恢复 EE 波段名。

规格是 ASCII JSON，最多 32768 字节，必须且只能包含以下字段：

```json
{"iterations":1,"offsets":[[-1,0],[0,0],[1,0]],"operation":"mean","skip_masked":true,"v":1}
```

`operation` 只支持 `mean`、`min`、`max`、`median` 和 `mode`。`offsets` 是 1–1089 个互异的 `[dx, dy]` 整数对，坐标分别表示列偏移和行偏移，正 `dx` 向右、正 `dy` 向下；范围为 -32–32，并严格按 `(dy, dx)` 排序。`iterations` 为 1–8。相邻 tile 之间每轮重新生成 halo，因此后续轮次使用上一轮实际输出。锁定的 GeoTrellis `BufferTilesRDD` 实现在正半径等于较小 tile 边长时可能产生空裁剪区域；原生入口会在缓冲前拒绝该边界。正半径必须严格小于 tile 较小边长；半径为零时允许单像元 tile，并直接执行无 halo 的 tile kernel。这个限制来自当前锁定版缓冲实现，而不是 focal 运算本身。

每个窗口忽略 NaN NoData。空窗口输出 NoData。`skip_masked=true` 时，中心像元若为 NoData，就保留 NoData；设为 false 时，有效邻居可以填补该中心。缺失邻居按 NoData 处理，缺失的整张源 tile 不会被合成成输出 tile；SpaceTimeKey 的邻域仅在同一时间键内计算。

输入像元转换为 Float64 后执行运算。min/max 直接保留最小／最大有限值；mean 将每个 binary64 值精确累积为 `2^-1074` 的整数单位，再执行一次最近偶数舍入的除法，因此不会因中间求和溢出或大小数相消而丢失残差；偶数样本 median 以精确二进制分数计算中点后舍入。mode 按有限数值相等计数，同频时选数值最小项；正零和负零作为同一个数值计数，输出规范为正零。这些统计边界和 mode 并列政策是明确的本地规则，尚未通过 GEE 同数据对照。

桥接在缓冲、复制像元或分配输出前计算预算：最多 100000 个源 tile、每 tile 10000000 个输入或缓冲解码单元、整个多轮缓冲最多 100000000 个解码单元；邻域、排序和缓冲工作总量最多 1000000000，每 tile 最多 100000000。预算包含迭代次数、偏移数量、median/mode 排序因子、对称 buffer extent，以及 34 个 64 位 limb 的精确累加成本（mean 每个邻值计入两个 limb 过程，并保守按八个过程计入除法／舍入；median 按十二个过程计入精确中点）。所有源 tile 在生成第一轮 halo 前逐一检查键、波段数、尺寸、有限值和 NoData。

`tests/test_ee_focal_kernel.py` 的 opt-in JVM 探针用独立 Python 全栅格参考检查五种算子、跨 tile 接缝、缺失源 tile、掩膜填补、多轮迭代、mode 平局和极大 Float64 值。它同时覆盖两条 seam 路径：手动组装 halo 来隔离内核索引，以及直接调用 GeoTrellis 的 collection `BufferTilesRDD` 重载来检查真实缓冲 API 的偏移、缺失邻 tile 和不合成输出 key 行为。另有 SpaceTimeKey collection 控制确认不同时间键不会互相提供邻值。探针不启动 SparkContext，因此不证明 Spark RDD 调度、完整 cube 任务、macOS 沙箱／服务／浏览器流程或 Google 数值一致性。

等于较小 tile 边长的正半径控制会在预检中被拒绝；锁定 GeoTrellis collection overload 的实际失败表现为 `GridBounds(3,0,2,1) do not intersect 3x2`。半径为零时，该 overload 也会尝试裁剪零宽邻接片段并失败，所以原生适配器直接对原 tile 执行 kernel，不调用缓冲 API。JVM 探针对较大邻域使用 3×4 tile 并仍跨越水平 seam；3×2 tile 控制保留半径 1 的水平和垂直接缝覆盖。
