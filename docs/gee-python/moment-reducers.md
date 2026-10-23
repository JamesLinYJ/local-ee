# 有限偏度与峰度归约

本地有限统计归约叶子实现 `ee.Reducer.skew()` 和
`ee.Reducer.kurtosis()` 的单输入形式。固定输出名分别为 `skew` 与
`kurtosis`；两个官方构造器均不接收参数。Google 的 API 文档只承诺计算偏度／峰度及给出输出名，没有规定样本偏差校正或峰度是否减 3，因而本地公式是明示的兼容子集政策，不声称 Google 数值一致。

本地 `skew` 使用总体标准化三阶中心矩，
`m3 / m2^(3/2)`，其中 `mr = sum((xi - mean)^r) / n`。本地 `kurtosis`
使用超额峰度 `m4 / m2^2 - 3`。不做有限样本偏差校正。该定义采用 NIST
手册给出的以 `n` 为方差分母的偏度与峰度形式；NIST 也说明减 3 是超额峰度的约定。

每次归约最多接收 1000 个单值行，累计工作仍受 50000 步上限限制。Null
值被跳过；其余值必须是有限浮点数或绝对值不超过 `2^53` 的整数。布尔值、字符串、非有限数和越界整数被拒绝。无有效值、单个有效值及常量样本返回命名的 `null`，因为其标准化矩不确定。

计算先按最大绝对值做精确二次幂缩放，再相对首值中心化，并按中心偏差范围缩放后计算矩。这样可以保留大共同偏移处可表示的增量，并避免原值的高次幂溢出或次正规尺度下溢。输出和输入行由调用方分别持有。

参考：Google [Reducer.skew](https://developers.google.com/earth-engine/apidocs/ee-reducer-skew) 与 [Reducer.kurtosis](https://developers.google.com/earth-engine/apidocs/ee-reducer-kurtosis) API 文档；NIST [Measures of Skewness and Kurtosis](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35b.htm)。这些来源没有提供 Google 与本地的同数据对照；精确数值的独立测试使用 `Decimal` 中心矩参考。
