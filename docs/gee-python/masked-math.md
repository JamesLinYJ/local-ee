# 保留小数掩膜的影像运算

一元科学函数、影像与有限未掩膜常量之间的运算，可以保留原始小数权重，
结果通过 `mask()` 读取权重或经 `sample`／`sampleRegions` 进入已有表格路径。
不把权重乘进科学值，也不把正的小数权重改成1。

```python
source = ee.Image(collection.first()).select('red').toDouble()
weighted = source.updateMask(0.25)
calibrated = weighted.multiply(0.0001).add(-0.1)
clamped = calibrated.clamp(0, 1)
root = clamped.sqrt()
weights = root.mask()
samples = root.sample(dropNulls=False, geometries=True)
expression = weighted.expression('sqrt(abs(b(0) * 2 - 1))')
```

## 支持路径

| 方法 | 范围 |
| --- | --- |
| abs、sqrt、log、log10、exp、round、floor、ceil、sin、cos、tan、Not | 一元；原Float32／Double科学计算边界保留 |
| add、subtract、multiply、divide、pow、mod、min、max | 一侧直接带权影像，另一侧为有限未掩膜标量／常量波段；保留顺序与广播 |
| eq、neq、gt、gte、lt、lte、And、Or | 同上；Boolean结果的0仍可有效，权重独立 |
| clamp、unitScale | 复用已审查的标量组合，要求有限low < high |
| toFloat、toDouble、float、double | 科学值转换，原权重幅值不随Float32舍入；溢出结果变缺测 |
| asin、acos、atan、sinh、cosh、tanh、cbrt、signum、gamma、digamma、trigamma、erf、erfc、erfInv、erfcInv | 原Float32特殊函数路径；Double科学值仍需显式toFloat |
| atan2 | 原Float32路径，一侧带权，另一侧为未掩膜常量 |
| expression | 已有算术／比较／逻辑／一元函数解析可用上述相同路径；多影像和条件分支未据此获得新支持 |

正反操作数都按官方波段配对规则处理，常量表达式先按已有的有限标量规则求值，
包括显式Float32阶段和Double类型声明。后续可接已有的筛选、训练、验证和CSV。
这些是同一组带权取样消费者，不代表带权影像的地图、区域统计或GeoTIFF已经接通。
常量折叠复用已有Double舍入政策，已经是整数的±(2^52+1)保持原值；
共享子树每次出现的完整深度仍计入原96层上限，不因折叠或缓存而跳过。
floor／ceil保留负零，负小数ceil到零时也保留负号，与现有原生计算统一；
否则后续atan2可能在负π与正π之间产生错误跳变。

## 输入、结果与权重

每次数学运算前，用闭合的 `apply(raw,1)` 校验真实输入。原始有效Infinity仍拒绝，
不能用权重0把非法源数据藏掉。这个guard沿用原科学精度声明，物理Double拷贝不等于
将原Float32运算提升为Double。

运算之后，独立的 `result_value` 投影保留有限结果的位值，把NaN或±Infinity变成NoData；
包含Float32转换溢出和域错误。再以结果有效性为旧mask、原权重为新值进行更新：
结果缺测时权重0，否则保留原权重。如此，值100加1后仍是101、权重仍为0.25；
对负数开方则该像元缺测，而不会让整块瓦片因结果Infinity失败。

`image_mask_math` 只改写直接carrier，保留原始影像及不可变权重谱系。
原50000工作／500节点预算不变；新建节点、常量扫描／求值、实际来源网格和时间检查
均保留计费。裸carrier仍不能进入未审查消费者。

## 尚未确认的语义

官方数学说明明确，多输入计算只返回共同有效像元；但没有给出两个独立小数掩膜
相遇时的通用幅值公式。因此本地的一元／未掩膜常量权重传递属于明确标注的实现推断，
没有Google数值等价声明；双栅格、两侧带权、ND／双影像expression、where／unmask、
球面部分像元clip、权重统计／透明度和栅格权重编码继续列为缺口。
`ee.Image().expression(...)` 的空接收者仍会序列化为未支持的mask setter，
该原始写法也保持为迁移缺口；本页示例使用已有带权影像作为expression接收者。
不猜测这些组合是取最小值或相乘。
[数学运算](https://developers.google.com/earth-engine/guides/image_math)、
[掩膜权重](https://developers.google.com/earth-engine/guides/reducers_weighting)。

验证分别记录官方双SDK离线图、独立数组参考、实际瓦片内核和物理CSV读回。
不自动调用Google，不把本地数值验证当作完整Spark、浏览器、私有数据或部署验收。

示例：[Python70](../../examples/70_GEE_python_masked_math.py)、
[JavaScript24](../../examples/javascript/24_带权影像运算.js)。
