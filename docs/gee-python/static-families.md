# 批量静态运算与数据整理

本批按五个算子族实现98个入口，每个入口都有固定官方SDK序列化和实际本地计算测试。它们处理已经解析的静态值，不自动开放同名 `Image.*` 栅格算法，也不代表完整GEE语义或Google数值一致性。

| 算子族 | 新入口数 | 主要能力 |
| --- | ---: | --- |
| Number | 25 | 三角与反三角、双曲、指数／对数、立方根、误差函数、Gamma、符号／逻辑、min／max、first、clamp、unitScale |
| Array | 36 | 对应逐元素数值运算，以及取整、选择、余数、幂、逻辑与六种比较 |
| List | 18 | 包含／相等／频数／位置／子序列搜索、插入／移除／替换／旋转／拼接、字符串连接及四种类型读取 |
| Dictionary | 10 | combine、fromLists、rename、size、map、toArray及四种类型读取 |
| String | 9 | 相等、正反搜索、切片、大小写、trim及JSON编码／解码 |

具体函数名及逐项参数签名保留在[机器清单](../../reports/gee-api-inventory.json)。官方算法目录中独立列出的别名同样计入入口数量，不能把别名数量或客户端可构造方法数量当作独立后端算法数量。

```python
scores = ee.Dictionary.fromLists(['red', 'nir', 'cloud'], [-2, 8, 15])
scores = scores.map(lambda key, value: ee.Number(value).clamp(0, 10))
scores = scores.rename(['cloud'], ['quality'])
print(scores.toArray(['red', 'nir', 'quality']).getInfo())  # [0,8,10]
print(scores.getNumber('nir').unitScale(0, 10).getInfo())   # 0.8

labels = ee.List(['water', 'cloud', 'land', 'water'])
print(labels.removeAll(['cloud']).replaceAll('water', 'wet').join('/').getInfo())
print(ee.Array([-7, 7]).mod(ee.Array([3, -3])).getInfo())    # [-1,1]
print(ee.String('  SCENE_2024  ').trim().toLowerCase().slice(0, 5).getInfo())
```

[示例38](../../examples/38_GEE_python_static_families.py)可离线构建并计算10项结果；测试另外使用官方JavaScript客户端构造相同表达式，进入同一个本地编译器逐项比较。示例不启动数据下载、模型训练、服务或导出。字典映射的 `[-2,8,15] → [0,8,10]`、归一化 `8/10`、标签连接、拼接和余数均有独立预期，三角往返按明确容差检查。

## 数值和数组

Number与新增严格数值路径拒绝非有限结果、实数域外运算和超出精确Float64域的整数输入（绝对值大于2^53）。浮点输入保留有限binary64值；不能据此宣称Google整数／dtype提升政策一致。`first` 等选择操作也检查另一个操作数，不把不支持的动态对象隐藏在未选分支。

Array保留原有rank≤8、10000单元和共享50000工作预算，只接受同形数组，无广播。实际NumPy／libm内核返回只读数组，不修改输入；整数幂在构造巨大整数前拒绝，负整数幂按有限实数处理。余数保留被除数符号；round沿用本地半入／朝正方向处理。非零除数、反三角／对数／Gamma定义域、溢出等有明确失败路径。libm舍入、极值和dtype与Google未作同数据对照。

`clamp` 要求min≤max；`unitScale` 不截断范围外数值，使用精确二进制有理数中间值避免可消除的溢出，边界相等时返回0是明确的本地政策。

## 列表和字典

新增List操作沿用有界结构比较，bool与数字区分，类型化Array保持形状／dtype规则。新入口对嵌套整数采用严格精确域校验；既有 `List.contains/distinct` 的历史结构比较政策保留，不全局改写旧行为。搜索、复制、结果增长和嵌套比较都消耗原有共享预算，10000元素是单独上限，不保证所有上限组合均可执行。

`rotate` 使用正数向右／负数向左的本地约定；官方简短描述未给出方向证明，不标记Google一致。join的数字／布尔／null格式按本地规则说明并测试。类型读取只返回已有匹配类型，不把字符串静默变成Number或把任意List伪装成Array。

Dictionary.map有限求值两参数序列化函数，返回null时丢弃键，闭包和结果需为受支持的静态类型。fromLists重复键保留最后一个值；rename要求源键存在，不允许重复源／目标，冲突只有显式overwrite才覆盖。这些碰撞／顺序政策未与Google比较。toArray支持已说明的数值／同形类型化数组与合法非负轴，保留键顺序；不支持任意动态对象。select／remove的正则选择器与toImage尚未实现。

## 字符串和JSON

偏移、长度、大小写和trim沿用Python Unicode码点／字符规则；没有Google UTF-16、语言相关大小写或空白规则一致性声明。搜索和大小写扩展在分配前计费。

JSON仅接受受支持的有限primitive／List／Dictionary；编码采用本地紧凑、排序键格式。解码拒绝重复键、非有限数、过大整数、超深／超大结构和不支持的内部对象；循环对象明确失败。字符串／JSON路径保留1MB、深度和共享工作上限，不执行嵌入文本或把JSON属性解释成流程指令。match／replace／split等正则算法仍未新增。

## 证据边界

本批证明固定SDK的构图、本地静态计算、声明的独立数值／结构预期和Python／JS结果一致；未运行Google服务端对照。现有栅格引擎／任务／地图／导出路径通过统一回归保护；本批未修改引擎，也未重新验收原生JVM／Spark、隔离运行器、浏览器或生产部署。
