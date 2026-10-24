# 影像集合匹配与合并

固定客户端：Earth Engine Python／JS 1.7.49。本地新增两个实际算法入口：
`Image.linkCollection`、`ImageCollection.combine`。Python 的
`ImageCollection.linkCollection` 是官方客户端提供的 map 辅助方法，最后调用同一个
`Image.linkCollection` 后端入口，不另计一个算法。

## 添加本地 QA 波段

```python
primary = local_collection.filter(ee.Filter.eq('side', 'primary'))
quality = local_collection.filter(ee.Filter.eq('side', 'qa'))
linked = primary.linkCollection(quality, ['qa'], ['qa_version'])
image = ee.Image(linked.first())
clear = image.select(['red', 'nir']).updateMask(image.select('qa').lt(50))
```

默认按 `system:index` 匹配。也可以显式指定平面属性名：

```python
linked = primary.linkCollection(quality, 'qa', 'qa_version', 'scene')
```

选中的波段、属性覆盖主影像的同名字段。没有匹配影像时，选中的波段全部为缺测，
选中的属性为 `None`；其他主波段的有效像元保持原样。因此对缺失 QA 再执行
`updateMask` 会使相应分析输出缺测，不能把没有 QA 的像元当作晴空。
未选中的主影像属性、实际来源身份及主影像足迹保留。显式选择
`system:index` 等属性时也按请求覆盖属性值，实际本地来源 ID 仍独立保留。

参数接受单个名称字符串或名称列表，不把字符串当作正则表达式。省略、`None` 和
空列表在本地均表示不选择该类字段；这项空值约定没有 Google 同数据对照。
实际匹配到的影像若缺少所请求的波段，应明确报错。匹配属性要求有限标量；
缺失／空属性不成为匹配键，多个次级影像具有同一非空键时明确拒绝。
不实现官方任意选择重复匹配影像的行为。

## 按 ID 合并集合

```python
kept = primary.combine(quality.select(['nir', 'qa']), overwrite=False)
replaced = primary.combine(quality.select(['nir', 'qa']), overwrite=True)
```

`combine` 是按 `system:index` 的内连接：只保留两侧都存在的主影像，顺序沿用主集合；
没有匹配时返回空集合。默认把同名次级波段改名为 `nir_1` 等未使用名称。
`overwrite=True` 在原波段位置替换同名波段。结果保留主影像身份、未更改的元数据
和足迹，不把两侧元数据无条件混合。两侧重复 ID 均拒绝。

## 本地边界与证据

每个输入最多 1,000 景，仍共享原有 50,000 步编译预算、500 节点及 1 MB 图限制。
上限不能同时视为规模保证。混合实际栅格前，需要重新核对来源、资产投影、网格、
时间及足迹证据；检查实际波段 DAG 的全部来源，不能只相信外层 Image 的来源字段。
当前要求每条来源只有一个观测、所有来源时间相同且原始足迹相等；这些是本地
执行边界，官方属性匹配本身不要求相同时间。无法证明对齐时拒绝，
不隐式重采样、时间广播或猜测 CRS。
仅在内存中合成的无界常量不能替代实际数据网格。

栅格对齐证明可以检查不同本地集合的来源，但没有放宽目录准入。
新增数据集仍需独立的兼容入库合同；任意声明一个目录 ID 不会自动获得 EE 加载权限。

[Python 示例63](../../examples/63_GEE_python_collection_link.py) 和
[JS 示例17](../../examples/javascript/17_集合匹配.js) 使用
[版本化合成样本](../../tests/fixtures/ee-collection-link-wave58-v1.json)：
三景主影像、两景 QA，显式固定网格和逐像元缺测值，包含缺失匹配、QA 覆盖、
自定义匹配属性、两种合并和云掩膜。两种 SDK 的本地图与独立逐像元预期分别检查。
这些是合成图计算证据，不是完整 Spark、部署、物理文件导出或 Google 一致性验收。

没有自动接入 `COPERNICUS/S2_CLOUD_PROBABILITY`。实际云概率产品需要先完成独立的
本地入库、版本、缩放、时间／网格和数据授权配置，不能把本例称为完整 s2cloudless。
