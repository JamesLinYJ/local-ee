# Double 栅格数组与矩阵

固定形状数组继续使用已有的逐元素 IR 和本地原生像元进程。
本批扩展显式 Double 精度，不引入另一套脚本解释器，也不把任意动态数组视为已支持。

## 精度与布局

单个数组波段可以调用 `toDouble()` 或 `toFloat()`，每个元素在指定位置实际转换，
保留形状、行优先顺序、数组名称和输入的共享掩膜。先转 Float32 再转 Double 不会恢复已丢失的位。
多个数组波段仍须先选择其中一个；不能直接导出数组，须用 `arrayFlatten` 或 `arrayGet` 转为标量波段。

求解、对角化、迹、行列式、范数及累积算法要求每个输入数组内部的所有元素都有统一的显式顶层 `toFloat()` 或 `toDouble()`。
这项本地合同避免从数值大小或元数据猜测精度；未转换和混合顶层转换的元素明确拒绝。
已有 Float32 路径保留逐步舍入，Double 路径使用原生 binary64 运算。
`matrixMultiply` 沿用已有逐项乘加规则，可直接消费这些算法的 Double 结果。

| 算法 | 有限实现范围 |
| --- | --- |
| `matrixSolve` | 保留常量满列秩设计路径；另支持实际栅格上的动态、欠定及秩亏设计，每轴1–8，A+B输入与结果分别不超过64元素 |
| `matrixInverse`／`matrixPseudoInverse` | 固定二维逐像元矩阵，逆矩阵要求方阵；[独立原生矩阵合同](pixel-matrices.md) |
| `matrixMultiply` | 单个固定二维数组，内维匹配，输出不超过64元素；逐项乘加 |
| `matrixToDiag` | 不超过8行的单列矩阵，构造方阵并实际填零 |
| `matrixTrace` | 1–8阶方阵，按对角线顺序相加 |
| `matrixDeterminant` | 1–4阶方阵，固定排列多项式展开 |
| `matrixFnorm` | 固定二维矩阵，先按最大绝对值缩放再计算 Frobenius 范数 |
| `arrayAccum` | 固定1–8维数组，沿已有轴计算前缀 sum、min、max；省略／null归约器代表sum |

这些形状上限不能保证所有组合都能编译：50000工作量和500图节点仍会拒绝过于复杂的输出。
共享掩膜表示输入数组的有效性；算术定义域错误和非有限结果沿标量原生政策成为 NoData，
不据此宣称与 Google 数组内部 NaN／dtype 行为等价。

## 常量设计矩阵求解

[官方 `matrixSolve`](https://developers.google.com/earth-engine/apidocs/ee-image-matrixsolve)
定义的是逐像元矩阵方程及超定系统的最小二乘解。本节说明保留的常量满列秩设计路径，
其设计矩阵为1–8行、1–4列且行数不少于列数，右侧为1–4列。
动态、欠定、秩亏及更宽的逐像元求解使用[新的有界原生矩阵路径](pixel-matrices.md)，
两条路径的秩判定与实际舍入分别记录。

设计矩阵逐层应用显式转换后，使用固定依赖 NumPy 的 `lstsq(A, I, rcond=None)` 计算伪逆，
再将其与真实右侧栅格组合。任一输入为 Double 时使用 Float64；两侧均 Float32 时保留原路径。
若字面量设计含非零常数预测列，Double路径在安全幅度内先减去每列的首观测，求解差值后恢复常数列系数，
减少大基线、小斜率的抵消。接近Double极限时，幅度检查关闭中心化，保留原伪逆乘加路径，避免新增相减溢出；
这条回退仍可能发生浮点抵消，不是任意极值下的精确解承诺。
设计和伪逆必须有限，绑定栅格的常量仍受既有 `±2^53` 域限制。
掩膜取两侧输入交集，名称／属性沿用左侧数组，实际来源可来自右侧栅格。

`rcond=None` 是本地 NumPy 的秩判定政策，见
[NumPy 说明](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html)。
当前固定版本内部即使接收 Float32 也使用 Double 计算类型，因此不能简单称为“Float32机器精度阈值”。
这里没有 Google／EJML 的分解算法、奇异值阈值或位级数值等价证据。

```python
design = ee.Image.constant(ee.Array([[1, 0], [1, 1], [1, 2]])).toDouble()
observations = image.select(['red', 'nir', 'blue']).toArray().toDouble()
observations = observations.arrayReshape(ee.Image.constant(ee.Array([3, 1])), 2)
coefficients = design.matrixSolve(observations)
predicted = design.matrixMultiply(coefficients)
```

## 数值与验证边界

行列式使用有限排列展开，容易受抵消和中间乘积溢出影响；它不是稳定 LU 分解的替代品。
范数采用缩放降低中间平方溢出的风险，最终结果仍须能用有限 Double 表示。
前缀和及乘加按实际操作顺序舍入，不承诺任意精度累计。

编译图的独立 NumPy／Fraction 数值参考、官方 Python／JavaScript 图一致性以及已有原生基础运算测试分别记录。
编译图解释验证不能代替完整 Spark 立方体、任务、浏览器、真实数据或 Google 同数据验收。

[Python示例56](../../examples/56_GEE_python_double_matrix.py) 与 [JavaScript示例10](../../examples/javascript/10_双精度数组回归.js)
串联3×2设计求解、预测、范数、迹、单值选择及精度控制。验证细节见 [第五十一批报告](../../reports/gee-python-wave51.json)。
