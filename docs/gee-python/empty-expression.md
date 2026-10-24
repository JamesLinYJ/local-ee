# 空接收者表达式与掩膜替换

官方 Python 与 JavaScript 客户端都把 `ee.Image()` 编码为常量0再设置零掩膜。
它有一个名为 `constant` 的透明波段，并非零波段影像。现在这条普通构造链可以
进入本地解码器，常见的空接收者、命名变量表达式可保留原写法：

```python
source = ee.Image(collection.first()).select(['red', 'nir']).toDouble()
result = ee.Image().expression(
    'nd = (x.nir - x.red) / (x.nir + x.red)', {'x': source})
samples = result.sample(dropNulls=False, geometries=True)
```

表达式中的 `x.red` 与 `x[0]` 读取指定变量；`b(...)` 读取接收者自己的波段。
上例没有使用透明接收者的科学值，所以实际网格来自 `source`。若公式使用接收者，
它的掩膜仍有效；不能因为接收者看起来“空”就删除它，或把透明值当普通零相加。
表达式编译器解析有界数据，不执行用户公式文本；所有声明参数即使未使用也需通过
影像类型检查。多栅格小数权重组合和多波段赋值等原有缺口继续明确拒绝。
创建实际数据load时检查每个所选资产的显式CRS／仿射矛盾，不能因为共享影像ID
或采用不同数据别名而忽略冲突。该边界避免每个算子重复扫描整棵表达式。缺少可选投影字段和跨观测Float32对齐保留已有路径，这不证明
跨观测重投影正确。严格掩膜／typed消费者仍有各自共同网格约束；输出scale／crs
不构成输入对齐证据。
Float32比较／逻辑回调显式保留每个栅格输入的缺测：底层Greater／Less会把NoData
变成false，兼容层在结果外恢复输入有效区交集，避免把缺测当有效0。原始有效false
仍是0。独立三像元控制和真实GeoTrellis算子组合分别保留原缺陷与修复结果。
底层And／Or／Not还具有位运算行为，因此逻辑And／Or先用 `x != 0` 归一化，
逻辑Not直接用 `x == 0`，内部有效性取反同样避免位取反。真实 `2、-3、0` 控制
分别保留原始错误值和规范化后的0／1结果；没有依赖NumPy逻辑默认值掩盖该差异。

## mask 与 updateMask

`mask()` 或 `mask(None)` 读取权重；`mask(new_mask)` 替换权重。
单波段新掩膜广播到全部输入波段，多波段按位置配对且数量必须一致。

```python
hidden = source.select('red').updateMask(0.25).updateMask(0)
restored = hidden.mask(1)
weights = restored.mask()
rows = restored.sample(dropNulls=False)
```

`updateMask` 不恢复旧权重为0的像元；setter 可以使其重新有效，科学值填为0，
不会找回被隐藏的原始观测值。已有有效像元保留值与负零，旧正小数权重也视为有效。
采用既有严格掩膜投影和原生 `unmask` 内核，保持原影像的有限支持、属性和精度声明。
源Infinity仍拒绝，不能通过旧零权重隐藏非法值。
原二值updateMask也在生成值／缺测条件前加入严格科学值校验，避免先把Infinity
擦成NoData再被setter误当普通缺测恢复；不会把二值输出改成小数权重carrier。

有限 `[0,1]` 掩膜范围、新掩膜自身缺测贡献0，以及已证明对齐的网格和时间轴，
是当前明确的本地合同。没有确认 Google 的越界截断、所有自掩膜情形或自定义
PixelType中最接近0的量化行为。带权结果只进入已审查的getter、算术和取样消费者；
统计、地图透明度、普通栅格导出和默认球面部分像元裁切仍待实现。

## addBands 与常量

有实际科学网格的目标影像可显式绑定有限带掩膜常量：科学值与权重分别绑定，
此前的Float／Double阶段与NoData保持。只有掩膜带来源、但科学值无来源的影像
不能反向借掩膜网格。独立常量影像不自动获得全球网格。

`overwrite` 接受布尔或缺省／null；冲突波段按原顺序加后缀，覆盖保留原位置。
显式 `names=[]` 按本地空选择合同不添加波段，不能贡献隐藏数据来源；这不扩展为
通用零波段影像支持。扫描、绑定、复制和后缀查找共用原50000预算；输入／输出
至多10000波段且仍受更严格的工作与500图节点限制，不能承诺上限可同时达到。

## 验证边界

双官方SDK离线编码、本地独立数组参考、真实GeoTrellis内核与可信合成CSV读回分别
提供语法、编译及本地数值证据。短时local[1]内核探针若通过，也不代表完整批处理、
沙箱、浏览器、私有数据或生产部署验收。复用不可部署审计JAR，不修改安装运行库。
没有Google计算或认证调用；只在极复杂且现有参考不足时另行讨论远端验证。

Python的 `ee.Image([])`／`ee.Image.cat()` 本身会在SDK构造时失败；JS的空常量编码
也不证明服务端零波段合同。默认全球投影／足迹、双栅格权重和其他签名差异继续列为缺口。

依据：[Image.mask](https://developers.google.com/earth-engine/apidocs/ee-image-mask)、
[Image.expression](https://developers.google.com/earth-engine/apidocs/ee-image-expression)、
[Image.addBands](https://developers.google.com/earth-engine/apidocs/ee-image-addbands)。
示例：[Python71](../../examples/71_GEE_python_empty_expression.py)、
[JavaScript25](../../examples/javascript/25_空影像表达式.js)。
