# 带小数掩膜的取样

`Image.sample()` 和 `Image.sampleRegions()` 可读取直接带小数掩膜的波段。
科学像元值与权重保持独立：值100、权重0.25的样本属性是100；权重0的位置缺测。
不同正权重不会改变取样概率，也不会把值乘成25。

```python
source = ee.Image(collection.first()).select(['red', 'nir']).toDouble()
weighted = source.updateMask(ee.Image.constant([0.25, 0.75]))
samples = weighted.sample(dropNulls=False, geometries=True)
valid = weighted.sample()  # 默认 dropNulls=True
training = weighted.addBands(ee.Image.constant(1).rename('class'))
points = training.sampleRegions(collection=regions, geometries=True)
classifier = ee.Classifier.minimumDistance().train(
    features=points, classProperty='class', inputProperties=['red', 'nir'])
```

`sample` 默认删除任一所选波段为缺测的行；`dropNulls=False` 保留相应 null 字段。
`sampleRegions` 继续在任一选中波段缺测时排除整行。保留实际像元中心、源身份、
行ID和输入波段顺序；空输出保持空表。
官方Python客户端序列化字面GeoJSON集合时可能省略Feature的 `id` 字段；
本地不会补造丢失身份，需要保留的来源标识可放在明确的属性中。
[sample参数](https://developers.google.com/earth-engine/apidocs/ee-image-sample)、
[sampleRegions示例](https://developers.google.com/earth-engine/apidocs/ee-image-sampleregions)。

## 可组合路径

- select、rename、addBands 可传递逐波段权重；toFloat／toDouble 及 float／double
  别名只转换科学值，不舍入掩膜。先toFloat再toDouble不会恢复已舍去的精度。
- 新增常量类别波段在原影像的有限网格和足迹内独立有效，不继承科学波段的掩膜。
  全局常量影像不能仅凭掩膜影像推断自己的有限网格。
- 样本可接已有 filter、limit、randomColumn、MD／Smile训练、验证、getInfo和CSV。
  缺测规则仍在这些操作前执行，原操作顺序、列谱系及训练／预测网格分别保留。
- sample 的 factor／numPixels 使用已有本地网格哈希，不按影像掩膜幅度加权。
  此随机算法尚无Google随机数或选中行等价保证。

编译器只在四个受控取样入口把直接carrier转换成 `mask_apply(value, weight)`。
同一个新视图同时用于节点／工作估计和实际编译，原SampledFeatures不被改写；
训练重代入继续复用同一真实取样表。保留50000工作、500节点及原有行／列／原生预算。
输入的实际网格和观测时间仍需证明兼容，不能以输出CRS／scale代替输入对齐。

## 限制与验证范围

带权影像经过尚未接通的算术、整数转换、where、unmask或clip后，取样仍明确拒绝，
不会递归剥去隐藏掩膜。带权科学影像的普通统计、透明度显示和栅格导出尚未接通；
`mask()` 返回的普通数值权重影像可进入已有数值路径。默认球面部分像元裁切仍待实现。

验证包含官方Python／JS离线序列化、实际GeoTrellis瓦片的掩膜应用与两种取样内核、
独立原始数组参考，以及取样行经现有任务／worker路径写CSV并用官方客户端读回。
该路径使用可信合成瓦片，不等同于完整Spark、隔离脚本、浏览器、私有真实数据或部署验收。
复用的原生JAR是不可部署的审计产物，未改安装依赖。没有调用Google计算或认证；
只有极复杂且文档／独立参考仍不足的算法，再单独讨论远端对照。

示例：[Python69](../../examples/69_GEE_python_masked_samples.py)、
[JavaScript23](../../examples/javascript/23_带权掩膜取样.js)。
