# 静态 Number / Array 特殊函数

本地编译器为固定 `earthengine-api` 1.7.49 的八个静态入口提供有限数值计算：
`Number.digamma`、`Number.trigamma`、`Number.erfInv`、`Number.erfcInv`，以及对应的
`Array.*` 方法。官方 SDK 离线序列化用于确认方法名和 `input` 参数；这项语法证据不表示 Google 服务端数值一致。

```python
ee.Number(0.5).digamma()
ee.Number(0.5).erfInv()
ee.Array([1, 0.5, -0.5]).trigamma()
ee.Array([0.5, 1.0]).erfcInv()
```

输入必须是静态有限实数。Number 拒绝布尔值、动态对象、非有限值和绝对值大于 `2**53` 的整数。Array 只接受有限实数 `StaticArray`，保留输入形状，包括带类型的空数组；每个数组结果使用 Float64，独立拥有只读存储。显式 PixelType 不参与此入口。

`digamma` 和 `trigamma` 对正数使用最多八步递推及渐近展开；负非整数使用反射公式，避免随输入大小增长的递归。非正整数极点拒绝。数学结果超出有限 Float64 范围时也拒绝。

`erfInv` 的实数定义域为开区间 `(-1, 1)`，`erfcInv` 为开区间 `(0, 2)`；端点、区间外值及非有限结果拒绝。逆函数的二分最多 64 次。`erfInv` 对接近零的输入采用局部级数，并按输入缩放搜索区间；上尾通过精确的 `1 - abs(input)` 转为直接 `erfc` 反演，避免 `erf` 接近 1 时的平台误差。`erfcInv` 不通过 `1 - input` 转换尾部。正尾大于 8 时使用固定 12 项的 `log(erfc)` 渐近展开和最多 8 次 Newton 更新，因此可处理最小正 Float64 次正规数；此处使用对数尾值，避免平台 `math.erfc` 把次正规输出量化到零。

运算在执行逐元素计算和结果分配前计入现有 50000 步静态编译预算。每个 Number 计入一次算子的完整上界；Array 的每个元素分别按最多 32 步特殊函数工作或 162 步逆函数工作预留。遇到数组中任一极点、域错误或非有限结果时，整个静态计算拒绝。

测试使用独立的 Euler 常数／闭式 Gamma 对数导数值、已知逆误差函数值及 `math.erf` / `math.erfc` 正向回代。`erfcInv` 最小次正规输入另与 100 位 Decimal 参考根对照，因为本机 `math.erfc` 在该尾部跳过一个次正规输出等级。测试通过离线官方 SDK 检查全部八个签名。此子集只说明本地静态 Float64 计算；不覆盖栅格像元、Spark、部署，也不声明与 Google 的数值或边界策略一致。
