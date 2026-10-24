# 零波段影像与集合累加

`ee.Image()` 有一个透明的 `constant` 波段。显式 `select([])` 才会删除所有波段，
可作为逐步加波段的初始状态；`rename([])` 只适用于已经没有波段的影像。
不要把透明波段当作零波段身份，也不要用未经客户端接受的空构造替代它。

```python
source = ee.Image(collection.first()).select(['red', 'nir'])

def append_band(name, state):
    return ee.Image(state).addBands(source.select([name]))

stack = ee.Image(ee.List(['red', 'nir']).iterate(
    append_band, ee.Image().select([])))
print(stack.bandNames().getInfo())
```

`addBands` 按调用顺序保留波段；`names` 选择源波段，不负责重命名。
同名波段缺省加数字后缀，`overwrite=True` 在原位置替换。
空源或 `names=[]` 不增加任何科学输入，不能给无网格常量提供隐藏来源。

## 元数据与像元执行

零波段影像仍可保存属性并读取 `bandNames()` 或 `getInfo()` 元数据。
元数据读取没有栅格流程图，不创建计算任务，也不加载被删除的波段。
直接地图、取样和栅格导出需要实际波段；不能把空对象伪装成成功生成的空文件。

结果继承第一幅影像的属性和足迹，这是官方 `addBands` 的合同。
源自已有影像的空目标仍须保留其有效足迹；后加影像的像元不能使原足迹以外的
区域变为有效。数据来源、空间足迹与像元网格分别检查，属性中的来源记录不是
加载被删除波段的许可。元数据及几何复制受原工作预算约束。
这里的栅格足迹分支限于已有平面Polygon／MultiPolygon路径；点、线、空几何和
球面足迹的栅格化不因此获得支持。读取 `Image.geometry()` 也不意味着后续
`Geometry.bounds()` 已实现，后者仍是明确缺口。

输入几何的有效边模型包含客户端默认值；省略 `geodesic` 的类型化多边形也可能是
球面几何。旧裁切／区域统计曾只看公开字段而漏掉默认值，本轮改为明确拒绝这些
尚未支持的球面路径。原来十一条错误接受的测试路径（十个去重公式）保留原式记录，显式平面写法另行验证，
不能把平面对照替代成默认球面兼容。

只有新增波段自身的实际科学值能提供有限网格。空目标中残留的目录身份、
仅存在于掩膜分支的来源、以及显式未选择的源波段，均不能给常量补出网格。
全球常量栅格仍未实现；向无科学网格的空目标单独添加常量是明确缺口。
后续普通常量和 `Image.metadata()` 的共享绑定器使用实际科学模板的临时网格
上下文，保留原来的影像身份、属性与首幅足迹；元数据来源不会重新变成像元来源。

波段正则选择复用有界RE2，使用完整匹配；环视、反向引用和字节转义不受支持。
4096字节模式、1MiB程序内存和共享工作预算是当前本地限制，不是Google配额。

## 有限 ImageCollection.iterate

`Collection.iterate` 使用官方 `collection`、`function`、`first` 参数。
回调依次接收当前影像与上一步结果；目录集合保留实际筛选和排序后的场景顺序，
显式集合保留构造顺序，逐景属性使用实际观测记录。

```python
def append_scene(image, state):
    return ee.Image(state).addBands(ee.Image(image).select('red'))

stack = ee.Image(collection.iterate(append_scene, ee.Image().select([])))
```

实际可接受规模还受到共享50000工作、序列化深度96和500个流程节点限制；
1000景的结构上限不代表1000景任意公式都能完成。
不同栅格的重投影、带权栅格的新消费者和球面部分像元裁切仍按各自合同检查。
空集合返回初始状态并检查回调中的算法名称与已收录的参数合同，不虚构一幅影像
来验证数据相关的类型或属性。省略／null初始状态保留null语义，不自动替换为0。

## 明确限制与验证口径

零波段与非空影像直接做二元算术仍明确拒绝，两个方向一致。
这是当前本地未支持边界，不能当作已经验证的 Google 报错规则。
新增波段后可使用其原有已验证的计算、取样和导出路径。
向已经裁切的目标绑定带小数掩膜常量仍有既存的不可变网格预检限制；普通常量的
绑定通过，不代表这个独立分支也通过。默认接收者 `b()` 与全局常量网格的其他
缺口继续列在[空接收者说明](empty-expression.md)。

官方 Python／JavaScript 离线序列化、本地编译、独立合成数值与物理 CSV 读回
分别记录。客户端接受一种写法不证明 Google 服务端结果；本轮不调用 Google
认证或计算，也不据组件测试声称完整 Spark、浏览器或生产部署验收。

完整示例：[Python](../../examples/72_GEE_python_bandless_accumulator.py)、
[JavaScript](../../examples/javascript/26_零波段累加.js)。
固定样本、原始失败和验收范围见[第六十八批报告](../../reports/gee-python-wave68.json)。

依据：[Image.select](https://developers.google.com/earth-engine/apidocs/ee-image-select)、
[Image.rename](https://developers.google.com/earth-engine/apidocs/ee-image-rename)、
[Image.addBands](https://developers.google.com/earth-engine/apidocs/ee-image-addbands)、
[ImageCollection.iterate](https://developers.google.com/earth-engine/apidocs/ee-imagecollection-iterate)。
