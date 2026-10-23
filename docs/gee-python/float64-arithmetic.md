# Double 影像算术

本批扩展已有的有界原生像元进程，使显式 Double 影像、整数转换和位运算结果可以继续进行基础计算。
官方客户端序列化、本地编译、原生瓦片数值、完整 Spark 服务以及 Google 同数据对照分别记录，不能互相替代。

## 支持范围

| 类型 | Image 方法 |
| --- | --- |
| 二元算术 | `add`、`subtract`、`multiply`、`divide`、`pow`、`mod`、`min`、`max` |
| 一元算术 | `abs`、`sqrt`、`log`、`log10`、`exp`、`round`、`floor`、`ceil`、`sin`、`cos`、`tan` |
| 逻辑 | Python 的 `And`、`Or`、`Not`，JavaScript 的 `and`、`or`、`not` |
| 已有精确比较 | `eq`、`neq`、`lt`、`lte`、`gt`、`gte` |

内部共有22种新增基础运算，不增加算法名称入口。至少一个操作数携带 Double 精度标记时，编译器使用原生 Float64 路径；已有 Float32 图保持原路径。
`clamp`、`unitScale`、`normalizedDifference` 和受支持的 `expression` 可复用这些基础操作。
这里的函数集合是固定的，不执行任意用户回调；Double 的 `where`、其他仅支持 Float32 的科学函数、动态数组及完整矩阵系统不由本批开放。

```python
nir = image.select('nir').toDouble()
red = image.select('red').toDouble()
ndvi = nir.subtract(red).divide(nir.add(red))
score = qa.toUint16().multiply(2).add(1)
```

整数转换、位运算及 `bitCount` 的数值结果保留 Double 标记，因此不必插入 `toFloat()`。
显式 `toFloat()` 会在那个位置转换精度，之后的 `toDouble()` 不会恢复已丢失的位。
两幅实际影像按已有波段广播规则配对；合并前必须有公共网格证据，不能用导出分辨率代替输入对齐证明。

## 数值、掩膜与常量

每一步按 binary64 计算并舍入；这里没有任意精度或融合整个表达式的承诺。
输入缺测时结果继续缺测；源数据中的无穷值会使计算失败。运算定义域错误或非有限结果则变为 NaN 缺测，有限下溢到0仍是有效结果。

- 除数为正零或负零时，`divide` 返回0，遵循固定签名及[官方 Image.divide 说明](https://developers.google.com/earth-engine/apidocs/ee-image-divide)的政策。
- `mod` 使用截断商对应的余数，符号随被除数；除数为0时结果缺测。
- `round` 采用本地“半值向正无穷”政策，避免先加0.5扰动大整数。该半值规则未与 Google 服务对照。
- 逻辑和比较输出0／1；Double 真值判断保留次正规数，输入不会先降为 Float32。
- 三角、指数、对数及幂采用 JVM StrictMath。独立参考检查的误差边界按算子记录，不代表 Google 位级一致性。

纯常量可绑定已有本地影像的有限网格；嵌套的 `toFloat`／`toDouble` 在指定位置应用。
现有常量网格的 `±2^53` 精确域、来源、足迹、循环及工作预算限制保持，独立／全球常量栅格仍不支持。

## 示例与数据边界

[Python 示例55](../../examples/55_GEE_python_float64_analysis.py) 和
[JavaScript 示例09](../../examples/javascript/09_双精度影像分析.js) 组合了：

- 合成 QA 打包、整数转换及后续 Double 算术；
- Double 反射率的 `normalizedDifference`，保留负输入与零分母掩膜；
- 显式归一化差值表达式，保留其不同的负值／除零政策；
- 显式合成的毫开尔文温度波段到摄氏温度的换算；
- `fastDistanceTransform().toDouble().sqrt()` 后进行像元长度换算。

温度分支需要名为 `synthetic_temperature_millikelvin` 的测试波段，单位mK、缩放0.001、偏移0。
测试只在元数据中声明它，没有生成或读取温度像元，也不声称普通本地影像、Sentinel-2 或 ERA5 已有该波段。
实际迁移时应替换成具有明确来源、单位和网格的自有温度数据。
示例显式将原始mK数值乘0.001；若入库产品已经标准化为K，只需减273.15，不能再次缩放。

## 验证与资源边界

固定形状数组的 `add`／`subtract`／`multiply`／`divide` 可以经既有逐元素展开使用这些原生操作。
双元素合成图与独立 NumPy 参考精确一致，包含超过 Float32 精度边界的值和整数组共享掩膜。
三景、单预测变量、过原点回归的 Double 系数图与独立 Fraction 参考在相对／绝对 `2e-15` 容差内一致；
同一案例的残差图超过既有编译预算，仍明确拒绝。缺少公共网格元数据的回归也拒绝。
这些是有限的合成图数值证据，不代表完整 Double 数组／矩阵引擎或栅格回归运行验收。

离线测试使用固定版本的官方 Python／JS 客户端，比较11项组合输出的本地图，并捕获地图和导出请求；没有启动任务或下载云端结果。
可信原生组件检查覆盖全部22种运算、掩膜、符号零、次正规数、溢出，以及温度、NDVI 和整数 QA 的组合计算；独立 Fraction／Decimal 参考和逐算子误差容限另存于批次报告。

内部继续使用历史名称 `local_ee_integer_values`，仅接收规范 v1 JSON 和一至两个输入波段。
1024字节规格、50000编译工作量、500图节点及1MB公共输出上限保持。
原生键、解码像元和工作量限制也保持，复杂函数有较高预充成本；规格合法不等于所有数据规模都能接纳。

这些证据不代替完整 Spark 任务、浏览器部署、私人真实数据或 Google 同数据验收。

批次验证和逐算子容差见 [第五十批报告](../../reports/gee-python-wave50.json)。
