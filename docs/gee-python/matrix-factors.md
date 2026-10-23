# 逐像元 Cholesky 与 LU 分解

本地固定形状 `RasterArrayImage` 为 `Image.matrixCholeskyDecomposition()` 和
`Image.matrixLUDecomposition()` 提供动态逐像元支持。两者都接收唯一必填参数
`image`，要求单个 rank-2 方阵，且矩阵每个元素来自同一像元的显式 `toFloat()` 或
`toDouble()` 波段。该支持沿用既有矩阵 SPI 的六字段 v1 规格；分解使用 `rhs_cols=0`。函数参数和命名因子分别对齐[官方Cholesky接口](https://developers.google.com/earth-engine/apidocs/ee-image-matrixcholeskydecomposition)及[官方LU接口](https://developers.google.com/earth-engine/apidocs/ee-image-matrixludecomposition)，数值政策单独说明。

```python
matrix = image.select(["m00", "m01", "m10", "m11"]).toDouble().toArray()
matrix = matrix.arrayReshape(ee.Image.constant(ee.Array([2, 2])), 2)

chol = matrix.matrixCholeskyDecomposition()
lower = chol.select("L")
chol_bands = lower.arrayFlatten([["row0", "row1"], ["col0", "col1"]])

lu = matrix.matrixLUDecomposition()
lower = lu.select("L")
upper = lu.select("U")
permutation = lu.select("P")
left = permutation.matrixMultiply(matrix)
right = lower.matrixMultiply(upper)
inverse = upper.matrixInverse().matrixMultiply(lower.matrixInverse()).matrixMultiply(permutation)
```

分解结果是逻辑命名数组波段容器：Cholesky 提供 `L`，LU 提供 `L`、`U`、`P`，每个
因子都是同形二维数组。先 `select("L")`、`select("U")` 或 `select("P")`，再调用
`arrayFlatten` 或矩阵运算。一次分解的各命名因子共享同一个 `local_ee_matrix_values`
生产者；选择单个因子不会重复计算整组结果。展平后的输出保持行优先顺序、原影像属性、
来源和整体矩阵掩膜。

合成示例在分解后求 `U` 的逆，并用 Cholesky `L` 做两步矩阵求解。完整的 2×2
LU 逆矩阵组合 `U⁻¹ × L⁻¹ × P` 也可在原有 50000 步预算内编译：根作用域的同一
SDK 因子引用复用不可变数值表达式，元数据在存储和读取时分别复制，各次实际网格校验保留。
该组合使用实际因子继续计算，并以独立 Fraction 逆矩阵验证；更大的组合仍可能超限。

每轴为 1–8，输入最多 64 个单元；Cholesky 输出最多 64 个单元。LU 同时返回三个
`n×n` 因子，因此 `3n²≤64`，最大方阵为 `4×4`。既有 8192 字节规格、50000 编译工作
步和 500 图节点上限保持；形状符合上限不保证复杂组合一定能通过全部工作预充。

Cholesky要求输入在binary64值上严格对称，并且由已舍入因子计算的每个原尺度残差主元严格为正。独立参考用Fraction表示原始binary64值及已舍入因子；残差先精确保留并无损转为Decimal，Inexact触发错误。仅开方和精确Fraction商的除法使用50位half-even Decimal上下文，再舍入回binary64。该过程避免全局归一化把极小的有效正定
主元压成零。任何缺测输入、非正主元或非有限因子都会使整个结果矩阵为 NoData；源影像
中的有效 Infinity 在进入数值核前拒绝。

LU 使用首个最大绝对值部分主元，`L` 对角线为 1，精确消元过程满足 `P×A=L×U`；返回的因子经过 binary64 舍入，该恒等式只在舍入精度下近似成立。换行时，`P` 和
`U` 一起交换，已经生成的 `L` 列也同步交换。将输入 binary64 值解释为精确有理数后，
主元、乘除和消元都保持精确；只在输出`L/U/P`时一次按nearest-even舍入回binary64；原生复用已有精确有理数输出取整内核，常量与独立参考使用直接Fraction→float转换。这样可以区分精确
零主元和虽很小但非零的主元。零主元或最终因子无法以有限 binary64 表示时，整组
`L/U/P` 都为 NoData；不以容差替换零主元，也不返回部分因子。

LU 在分解前扫描实际源瓦片，只归并指数／有效位数包络和瓦片计数，按该包络预充精确有理数运算工作；输出时再次核对同一包络。空包络和全零包络不会把全负指数范围扩大到 0。原有每瓦片 1 亿、总计 10 亿工作上限保持。预算函数的可信瓦片检查允许普通 2×2 整数矩阵的 128² 瓦片和二进制小数矩阵的 256² 瓦片；横跨 `1e308` 与最小次正规数的 2×2 矩阵，单像元允许，重复为 4×4 像元时拒绝。这些是资源准入检查，未测量大瓦片吞吐，也未执行完整 Spark RDD 准入路径；后者仅经过源码审查。预算估算不保证硬 CPU 时间上界，执行器仍需超时终止。

显式 Float32 输入会先按 Float32 边界舍入；嵌套的 `toFloat().toDouble()` 保留该输入
舍入，再以 Double 精度继续计算。原生分解以 Float64/NaN 物理值输出，已有外层类型
恢复再把 Float32 输入的因子转换为 Float32；有限 Double 因子也可能在这一步溢出为
Infinity。该输出转换溢出与数值核内导致整矩阵 NoData 的非有限因子分开处理。实际
SDK 序列化、离线编译和独立合成图数值检查不代表 Google 数值一致性，也不代表完整
Spark、部署、浏览器或私有真实数据验收；独立图求值器只覆盖受限本地像元路径，不是
Spark 运行时。

示例 [59](../../examples/59_GEE_python_matrix_factors.py) 和
[JavaScript 13](../../examples/javascript/13_矩阵分解.js) 使用显式声明的合成目录，
只编译图，不访问 Earth Engine 服务或私有影像。定向回归为
`tests/test_ee_matrix_factor_workflow.py`，独立 Fraction/Decimal 参考为
`tests/ee_matrix_factor_reference.py`。

`Image.matrixTranspose`与固定版本`arrayTranspose`签名一致，默认交换轴0和1，也可指定合法固定轴；直接复用布局逻辑而不做数值转换，保持嵌套类型转换及整个数组掩膜。
