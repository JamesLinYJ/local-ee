# 整数影像、QA 位运算与精确比较

本批通过固定版本的官方 Python／JavaScript 客户端接入整数影像操作。
客户端能序列化、编译器能生成本地图、实际瓦片数值正确及 Google 同数据一致性是不同的验证层级。
本页说明已实现的有限范围。

## 类型转换

下表各行的方法使用同一项本地转换政策：

| 目标范围 | Image 方法 |
| --- | --- |
| `uint8` | `byte`、`toByte`、`uint8`、`toUint8` |
| `int8` | `int8`、`toInt8` |
| `int16` | `short`、`toShort`、`int16`、`toInt16` |
| `int32` | `int`、`toInt`、`int32`、`toInt32` |
| `uint16` | `uint16`、`toUint16` |
| `uint32` | `uint32`、`toUint32` |
| `int64` | `long`、`toLong`、`int64`、`toInt64` |

本地转换将有限值向零截断，并限制在目标范围内；`int64` 只接纳结果在
`[-2^53, 2^53]` 内的转换。物理存储统一使用 Double 和 NaN 缺测值，避免有效的
`-128`、`-32768` 和 `Int.MinValue` 与整数缺测值哨兵冲突。
这不表示完整 Int64 存储、Google 舍入或整数类型传播已经兼容。

所有整数转换、位运算及 `bitCount` 的数值结果都保留 Double 精度标记。
常量折叠也保留该标记，避免后续比较悄悄转成 Float32。
普通像元算术仍需显式 `toFloat()`；转换后允许精度损失。
常量可通过 `addBands` 绑定已有本地影像网格，独立／全球常量栅格仍不支持。
仅用动态掩膜包裹无来源常量也不能建立已支持的 Double 栅格，会明确报错。

## 位运算与比较

支持 `bitCount`、`bitwiseAnd`、`bitwiseNot`、`bitwiseOr`、`bitwiseXor`、
`leftShift`、`rightShift`，以及官方单列别名 `bitwise_and`、`bitwise_not`、
`bitwise_or`、`bitwise_xor`、`left_shift`、`right_shift`。

位运算的实际输入和结果必须是 `[-2^53, 2^53]` 内的有限整数。
运算采用有符号 64 位补码，`bitCount(-1)` 为 64；右移保留符号。
移位数必须为 0–63 的整数，左移不回绕，超出精确结果范围会报错。
固定参数会在读取像元前校验，整张影像缺测也不会掩盖非法移位或小数位掩码。
两幅影像按既有单波段广播／等波段自然顺序配对，使用各自掩膜的交集。
不同实际来源必须先证明网格一致，不能靠导出分辨率推断输入已对齐。

已有的 `eq`、`neq`、`lt`、`lte`、`gt`、`gte` 在 Double 输入上采用原生
Float64 比较，保留高位整数、次正规数及 `-0 == +0` 的数值语义，输出为 0／1。
原有 Float32 比较路径保持不变。比较结果可继续作为普通布尔掩膜使用，
这不开放通用 Float64 算术。

```python
scene = ee.ImageCollection('sentinel-2-l2a').first()
scl = scene.select('SCL').toUint16()
# 演示自定义 QA 布局，不是产品 QA60。
qa = scl.eq(8).leftShift(0).bitwiseOr(scl.eq(9).leftShift(1))
clear = qa.bitwiseAnd(3).eq(0)
result = scene.updateMask(clear)
```

JavaScript 中普通 `1 << 40` 会先执行 JavaScript 的 32 位移位；传递高位常量
应写 `2 ** 40`，或使用受支持的 EE 数字移位表达式。

## 示例、接口及验证边界

[Python 示例54](../../examples/54_GEE_python_integer_images.py) 和
[JavaScript 示例08](../../examples/javascript/08_合成QA整数影像.js) 使用本地集合
`sentinel-2-l2a` 的 `SCL`、`NIR`、`red` 波段，要求选定数据确实具有这些名称。
在工作台运行时会读取已有本地影像；本批测试只提供合成元数据并捕获地图／导出请求，
没有读取用户栅格文件。

示例的位布局明确为自定义：0–2 位标记 SCL 8、9、10，3 位标记类别3，
4 位标记类别11，5–6 位标记类别0、1。它不复制 Sentinel-2 QA60、Landsat
`QA_PIXEL` 或任何其他产品的 QA 定义。反射率在 `normalizedDifference` 前明确转为 Float32。
另有栅格来源的 40 位操作、`2^24 + 1` 比较，以及仅含 0／`2^53` 的边界输入。

内部 `local_ee_integer_values` 只接受一至两个有序输入波段及至多 1024 字节的
规范 v1 JSON。常量使用有限 binary64 的十六进制位串，不含用户函数或执行文本。
实际输入须具有 `band0[,band1]` 标签，输出为 `v`；编译器恢复用户波段名。
由于固定上游的 dry-run 会丢失 rename／merge 后的准确波段元数据，预检查只返回
已知的单波段输出结构并保留全部来源轨迹，不推测输入顺序或虚构像元。
实际立方体和原生层仍执行输入校验。

原有 50000 编译工作量、500 图节点和 1 MB 公共输出限制保持。
原生输入至多 100000 个键，每瓦片／总解码像元上限为 1000 万／1 亿，
本算子的工作预算为每瓦片 1 亿、总计 10 亿；接纳范围不等于吞吐承诺。

验证包含官方客户端离线图一致性、上游实际流程图求值器的结构路径、独立 Python
整数参考和真实 GeoTrellis 瓦片计算，包括掩膜、溢出和多步合成 QA 链。
它们不代替完整 Spark 服务、浏览器部署、真实数据或 Google 同数据验收。
