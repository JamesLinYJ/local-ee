# 影像数学与数值准备

固定客户端为 `earthengine-api` 1.7.49。Python 与 JavaScript 共享下列编译和计算路径。可信组件验证不表示已部署到当前工作台，也不是 Google 同数据一致性结论。

## Image 语法

| 调用 | 计算 | 实数域与本地边界 |
| --- | --- | --- |
| `image.asin()` / `acos()` / `atan()` | 反三角函数，弧度 | asin／acos 输入为 [-1,1] |
| `x.atan2(y)` | 方向角 | 按固定签名的 x、y 约定调用 JVM atan2(y,x)，保留四象限和有符号零 |
| `image.sinh()` / `cosh()` / `tanh()` | 双曲函数 | Float32 溢出则掩膜 |
| `image.cbrt()` / `signum()` | 实数立方根／符号 | 支持负数立方根；signum 保留零符号 |
| `image.gamma()` | Gamma 函数 | 非正整数极点掩膜 |
| `image.digamma()` / `trigamma()` | Gamma 对数一、二阶导数 | 极点掩膜；负非整数用反射公式避免逐步递归 |
| `image.erf()` / `erfc()` | 误差函数／余误差函数 | 固定 Commons Math 的 erf(-0) 返回 +0 |
| `image.erfInv()` / `erfcInv()` | 逆误差函数 | 有限实值输入分别为 (-1,1) 和 (0,2) |

使用真实 JVM Math 和固定的 Apache Commons Math 3.6.1，没有占位算法。每次运算在实际 Float32 输入上计算并舍入为 Float32；NaN、无穷输入、无实数结果、极点、非有限结果和 Float32 溢出成为 NaN NoData。下溢可能成为有符号零。

默认未指定类型的源像素和常量通过图中明确的 `local_ee_to_float` 转换。例如整数 16777217 转为 Float32 后为 16777216，本子集不保留该精度。显式 `toDouble()` 输入会被拒绝，必须明确 `toFloat()`；结果之后可以 `toDouble()`，但不能恢复已损失的精度。

```python
# coefficients 是已有有限本地影像，含 cosine、sine 波段。
coefficients = coefficients.toFloat()
phase = coefficients.select("cosine").atan2(
    coefficients.select("sine")).rename("phase")
bounded_angle = coefficients.select("sine").clamp(-1, 1).asin()
```

保留普通 Image 波段配对、单波段广播、输出命名、接收者属性、掩膜和观测谱系。`atan2` 的两个实际栅格操作数要求相同的已证明来源谱系；不同集合／条目分支不能通过隐式最近邻重采样合并。通用投影／网格对齐尚未实现。

纯常量数学没有独立全球栅格，需要与真实影像结合：

```python
gamma_one = ee.Image.constant(1).gamma().rename("gamma_one")
result = phase.addBands(gamma_one)
shifted = phase.add(ee.Image.constant(0.5).erfc())
```

需要常量绑定的 `ImageCollection.map` 复用既有逐条目展开；普通栅格一元运算保留紧凑路径。展开受原有条目、50000 编译工作和 500 节点限制，不增加隐式时间广播。常量采用目标有限网格和范围，不能据此查询其全球默认投影。见[示例39](../../examples/39_GEE_python_pixel_math.py)。

## 静态数组和数字

```python
qa = ee.Array([1, 2, 4, 8]).bitwiseAnd(ee.Array([5, 5, 5, 5]))
qa.bitCount()                              # [1, 0, 1, 0]
ee.Array([3, 4]).dotProduct(ee.Array([3, 4])) # 25
ee.Array.identity(2)                       # [[1,0],[0,1]]
ee.Array.identity(0)                       # []，内部形状 (0,0)
ee.Array([1, 2]).pad([4], -1)               # [1,2,-1,-1]
ee.Number.parse("101", 2).bitwise_and(4)  # 4
```

Array 新增 `bitCount`、`bitwiseNot`、`bitwiseAnd`、`bitwiseOr`、`bitwiseXor`、`leftShift`、`rightShift`，以及官方单列的六种蛇形别名；Number 的六种别名复用既有整数实现。Array NOT 是有符号补码取反，bitCount 按 64 位补码统计；AND／OR／XOR 仅接受非负同形数组，左移要求非负且不溢出，右移为有符号右移。移位数为 0–63，可为标量或同形数组。

静态 Array 保留 rank≤8、10000 单元、精确整数绝对值≤2⁵³、共享 50000 工作预算和 1MB 公共输出限制。位运算不支持空数组，identity(0) 可产生有类型空数组。dotProduct 要求等长一维数组：整数精确累加，浮点乘积以有理数累加后一次转 Float64。pad 只在轴末尾补齐至至少所需长度，不截断；省略／null 填充值为 0。输入不被修改，数组结果独立只读；没有新的 PixelType 或一般广播能力。

`Number.parse(input, radix)` 接受最多 256 字符的静态 ASCII 字符串。radix 省略／null 时为 10，可含小数和指数；其他 2–36 进制只接受完整有符号整数，不接受前缀／部分解析。拒绝非有限数和超出精确整数域的值，保留负零；极端下溢成为有符号零是明确本地政策。

## 验证边界

每个新增入口都有实际固定 SDK 序列化和本地编译检查。原生瓦片验证覆盖 16 个数学算子、独立闭式／数值参考、域错误、负次正规数、掩膜、Float32 舍入、atan2 四象限／零符号和非法输入。依赖摘要写入独立适配器清单，没有下载依赖或覆盖已安装运行环境。

引擎继续验证有限网格、键、波段、瓦片形状和原有解码上限；额外像元计算工作上限为 67108864，输出分配前检查。独立瓦片证据不覆盖完整 Spark RDD、沙箱批任务、浏览器、部署或 Google 结果对照。邻域／focal 尚未实现。
