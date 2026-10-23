# 逐像元矩阵运算

本地固定形状 `RasterArrayImage` 为 `Image.matrixInverse()`、
`Image.matrixPseudoInverse()` 和动态 `Image.matrixSolve(image2)` 提供有界支持。
官方 Python／JavaScript SDK 保持原调用形式；矩阵单元可以来自影像波段，也可以是有限常量。
下面的 `A` 与 `B` 都由真实影像波段构造，示例不把设计矩阵写成字面量：

```python
source = image.select(['m00', 'm01', 'm10', 'm11', 'b0', 'b1'])
A = source.select(['m00', 'm01', 'm10', 'm11']).toDouble().toArray()
A = A.arrayReshape(ee.Image.constant(ee.Array([2, 2])), 2)
B = source.select(['b0', 'b1']).toDouble().toArray()
B = B.arrayReshape(ee.Image.constant(ee.Array([2, 1])), 2)

inverse = A.matrixInverse()
pseudo = A.matrixPseudoInverse()
solution = A.matrixSolve(B)
prediction = pseudo.matrixMultiply(B)
reconstruction = pseudo.matrixMultiply(A)
```

矩阵结果保留固定二维形状；用 `arrayFlatten` 或其他已支持的数组访问器，才会把单元变成普通影像波段。输出按行优先顺序排列。`matrixSolve` 接受动态 `A` 与 `B`，输出形状为 `(A 列数, B 列数)`；超定系统采用最小二乘解，欠定或秩亏系统采用最小范数解。伪逆可处理矩形和秩亏矩阵。

矩阵值进程的规范 v1 规格包含操作、`rows`、`cols`、`rhs_cols` 和按行优先排列的单元描述。实际输入波段用连续的 `band` 索引引用；常量使用 16 位小写 IEEE-754 binary64 十六进制。进程会重新核验输入波段数、矩阵尺寸、时间轴、网格、像元键和掩膜。规格最多 8192 ASCII 字节；每轴为 1–8，输入和输出分别最多 64 个单元。旧的数组单元、图节点、编译工作量和栅格预算仍然适用，因此符合这些矩阵上限也不保证某个最大组合可编译或运行。

本地数值政策使用缩放后的 SVD，截断阈值为 `eps(Float64) × max(rows, cols)` 乘最大奇异值。`matrixInverse` 的数值奇异矩阵、任一输入单元缺测，以及产生非有限结果时，都会把该像元的整个结果矩阵设为 NoData；有效输入 Infinity 会拒绝计算。`matrixPseudoInverse` 和 `matrixSolve` 使用同一阈值。其秩判定、退化矩阵结果和舍入属于本地实现政策，不代表 Google Earth Engine 数值一致性。

原生矩阵内核的物理输出为 Float64。编译器仍按 EE 输入类型联合规则处理可见类型：若所有矩阵输入均为 Float32，会在矩阵进程之后显式转换回 Float32；任一输入为 Float64 时保留 Float64。嵌套的 `toFloat().toDouble()` 仍保留先发生的 Float32 舍入，不会恢复被舍弃的位。

上述整矩阵非有限结果政策作用于原生 Float64 内核。后续既有 `toFloat` 边界按 IEEE 转换：原生有限结果若超出 Float32 范围，可以成为 Infinity，不会自动把整个矩阵重新置为 NoData；需要较大动态范围时应在输入处明确 `toDouble()`。纯常量折叠遇到最终 Float32 溢出会明确拒绝。这两条边界已有不同的可表示性限制，尚未做 Google 对照。

求解对原始 RHS 使用精确二进制值的 BigDecimal 乘加；不能先用 RHS 的最大值归一化，否则很小但可恢复的系数会丢失。只有满列秩且存在非零常数预测列时，才对 RHS 精确中心化并恢复截距。较小的固定满列秩字面量设计继续保留既有 NumPy `rcond=None` 与标量乘加路径，具体舍入和极值回退见 [Double 数组](double-raster-arrays.md)。纯常量逆／伪逆可在有限输出时折叠；纯常量奇异逆无法表示带网格的缺测，因此明确拒绝，不创建全球栅格。

原生矩阵按尺寸预充每瓦片1亿、总计10亿的工作估算，另有既有解码、像元和键上限。该估算包含精确乘加开销，符合形状上限的较大瓦片仍可能超限。上游 SVD 没有显式最大迭代数；固定小尺寸和有限输入不等于严格指令或时延保证，实际执行保留已有任务墙钟超时。

当前预算检查中，2×2矩阵、单列RHS求解每像元计2520，单瓦片最多39682像元：128×128通过，256×256拒绝。2×2逆矩阵每像元计400，128×128和256×256均通过。这里验证的是预算准入边界，实际数值探针使用小型合成瓦片；这些数值不是吞吐或完整 Spark 验收。

验收证据分层记录：官方 Python／JavaScript SDK 序列化和本地编译、独立 NumPy 样本图参考、实际 GeoTrellis 瓦片内核是不同层次。样本图参考只解释已编译的合成图，不运行 Spark。单独的内核结果也不表示完整 Spark 批任务、任务文件发布、服务／浏览器交互或 Google 同数据对照已通过；没有对应实测记录时，不应据此扩大支持范围。

Cholesky与LU的命名因子、源常量折叠、原尺度数值和资源准入见[矩阵分解](matrix-factors.md)。`matrixTranspose`使用与`arrayTranspose`相同的固定轴交换合同，可以直接消费已选取的因子，保持单元、掩膜和声明精度。
