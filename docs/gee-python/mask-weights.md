# 小数掩膜与权重读取

`Image.updateMask(mask)` 可以保留逐波段的小数权重，`Image.mask()` 将权重作为
普通数值影像返回。科学像元值、掩膜权重和 NoData 分开表示；例如值100、权重0.25
的像元仍然保存值100，读取掩膜得到0.25，不把科学值改成25。

```python
source = ee.Image(collection.first()).select(['red', 'nir']).toDouble()
weighted = source.updateMask(ee.Image.constant([0.25, 0.75]))
weights = weighted.mask()                       # 仍叫 red、nir
nir_weight = weighted.select('nir').mask()      # 保留该波段的0.75权重
replaced = weighted.updateMask(0.5).mask()
```

掩膜单波段广播到全部输入波段；掩膜有多个波段时必须与输入数量相同，按位置配对，
结果保留原波段名。权重须在有限的 `[0,1]` 范围内；常量在编译时校验，真实栅格
在内核中再次校验。源 NoData 的权重为0；新掩膜的 NoData 也贡献0。零权重作为
getter 输出中的有效数值保留。Infinity 拒绝，不能先转成 Float32 后误判有效性。

组合采用官方 API 文字所述的“在原掩膜非零处更新”：原权重为0时保持0，否则
采用新掩膜值；不擅自改成相乘或取最小值。新掩膜影像自身被掩膜的位置贡献0。
这属于按文档实现的本地规则，尚未用 Google 计算结果确认小数掩膜组合的精确行为。
[updateMask](https://developers.google.com/earth-engine/apidocs/ee-image-updatemask)、
[mask](https://developers.google.com/earth-engine/apidocs/ee-image-mask)。

## 当前可用路径

编译器以不可变 `with_mask(value, weight)` 保存独立权重；select、rename 和 addBands
可传递它，getter 才物化普通数值波段。三个闭合的本地投影处理真实栅格：

| 投影 | 输入 | 输出 |
| --- | --- | --- |
| validity | 原科学值 | 有效值1、NoData0 |
| update | 旧权重、新掩膜值 | 旧权重非零处的新权重 |
| apply | 原值、独立权重 | 权重非零处原值，否则NoData；供受控掩膜输入和取样入口使用 |

底层返回单波段 Float64，保留实际网格、空间／时间键与源属性。组合前重新检查
真实来源、资产网格和时间维；不能用导出的 CRS／scale 作为输入已经对齐的证据。
常量只在已存在的有限栅格上物化，不构造全球网格或虚假观测。
保留原50000编译工作、500节点及原生键／解码上限，掩膜处理另有67108864工作预算。

**权重读取与直接带权波段的取样已接通，下游尚未全部接通。**
`weighted.sample()`／`sampleRegions()` 保留正权重处的原科学值，零权重按原取样缺测规则
处理，可接已有训练／验证／CSV；不按权重幅度调整取样概率。Float／Double转换只转换科学值。
详见[带掩膜取样](masked-sampling.md)。直接对 `weighted`
做算术、区域／时间统计、unmask、地图或导出会明确拒绝尚未实现的消费者，不能
静默降为二值掩膜。`weighted.mask()` 返回的是普通数值权重影像，可继续使用已有
数值影像路径；这不代表权重已被统计或显示为原科学影像的透明度。mask setter
仍未实现；缺省或显式 null 的 getter 都可用。原二值 updateMask 路径继续保留。

## 与裁切、统计的关系

GEE 文档明确说明 clip 可能产生部分像元掩膜，默认归约器使用掩膜权重。
因此只判定像元中心是否在多边形内，不足以实现默认 clip。下一步需要在真实网格
生成覆盖权重，并接通带权运算、统计、显示及输出；这份权重表示是共同基础。
[加权归约说明](https://developers.google.com/earth-engine/guides/reducers_weighting)。

reduceRegion 的区域交叠权重与影像自己的掩膜是不同输入。其8位区域权重量化
不能直接当成 clip 掩膜的精度规定。精确 clip 覆盖公式、球面边映射到像素网格的
误差策略，以及 clip 后 `system:footprint` 的精确行为仍需分别确认。
默认球面裁切、线／点裁切和 clipToCollection 继续列为缺口；没有将它们替换成
二值中心点裁切，也没有修改原始 STAC 足迹的科学模型。

本地验证使用官方两个 SDK 的离线序列化、独立 Fraction／Decimal／NumPy 基准与
实际 GeoTrellis 瓦片内核。它们分别证明语法、编译和本地数值行为，不等同于完整
Spark 批任务、浏览器、私有真实数据、部署或 Google 同数据验收。不自动调用 Google；
只有特别复杂、文档和独立基准仍无法确认的行为，再单独讨论受控对照。

离线示例：[Python68](../../examples/68_GEE_python_mask_weights.py)、
[JavaScript22](../../examples/javascript/22_小数掩膜权重.js)。
