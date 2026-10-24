# 颜色转换与多步定标

`Image.rgbToHsv()` 与 `Image.hsvToRgb()` 可与波段选择、重组、Double 算术和显式 Float32 转换组合。输入顺序分别是 RGB 与 HSV，各需恰好三个波段；输出名分别是 `hue/saturation/value` 和 `red/green/blue`。

```python
rgb = image.select(['red', 'green', 'blue']).toDouble()
hsv = ee.Image(rgb.rgbToHsv())
half_hsv = (
    hsv.select('hue')
    .addBands(hsv.select('saturation'))
    .addBands(hsv.select('value').multiply(0.5).rename('value'))
)
darker = half_hsv.hsvToRgb()
calibrated = (
    rgb.rgbToHsv().hsvToRgb()
    .add(0.05).toFloat().toDouble().max(0).min(0.65)
)
```

输入必须先按实际数据的缩放和单位准备到 `[0, 1]`；本地转换不会自动归一化或截断。任一输入缺测或超出这个域时，结果为 NoData。灰度／黑色的 hue 为 0；HSV 的 hue=1 与 hue=0 相同。这些是当前本地规则，不代表已完成 Google 同数据对照。`toFloat().toDouble()` 保留中间 Float32 舍入，不能作为无损转换消除。

完整 Python 示例见 [示例64](../../examples/64_GEE_python_scalar_composition.py)，对应 [JavaScript 示例18](../../examples/javascript/18_颜色组合与定标.js)。命令只编译版本化的两景合成样本，不启动后端或读取本机科研数据：

```sh
.venv/bin/python examples/64_GEE_python_scalar_composition.py
.venv/bin/python -m pytest -q tests/test_ee_scalar_composition_workflow.py
```

## 组合预算

第五十九批修复重复构造、扫描共享表达式的问题，没有提高原有上限：50000 编译工作量、500 个图节点和 1 MB 序列化大小继续生效。

| 固定合成流程 | 修复前 | 修复后工作量 | 节点数 |
| --- | --- | --- | --- |
| RGB→HSV→RGB 控制流程 | 49618，接近上限 | 36386 | 172 |
| 分别选择 HSV 通道，将 value 减半后重组为 RGB | 超限拒绝 | 43880 | 205 |
| RGB 往返→加0.05→Float32→Double→截到0–0.65 | 超限拒绝 | 40956 | 196 |

这些数字来自固定样本和固定 SDK 序列化；改动脚本、元数据或数据规模可能再次触及预算。步骤计数不是运行耗时，也不是吞吐性能。两个组合流程的 Python／JS 输出图相同；每个客户端检查72个样本单元，其中60个有限、12个缺测，最大观察绝对误差9.72e-17。数值比较使用独立 colorsys、Fraction 和 NumPy Float32 参考及合成图解释器，没有新增 GeoTrellis／完整 Spark／浏览器或 Google 验收。

## 内部约束

- 只复用根作用域中明确列出的 RGB／HSV `ValueRef`。mapped／函数回调使用各自环境，单次编译最多64个颜色快照，并受原500项根缓存上限约束。
- 冻结的 Pixel／Source 可共享身份；波段列表、属性和足迹各自拥有副本。非 JSON、可变或循环后代保持原求值路径。
- 图内的工作账本最多4096项，按实际相同 Pixel 身份复用已付过费的不可变子树；保存子树高度，在每次命中时重查深度。未知、模型或可变载荷仍执行原估算并计入额外检查。
- 每次操作仍完整计入规格、波段包装和节点预检；来源、目录、时间轴及像元网格重新验证。缓存不构成新的数据准入或重投影证明。

较大图、解混默认256²瓦片和一般矩阵组合仍有原有资源限制。此批没有新增算法名称，名称清单仍为693／991；这不是完整语义或迁移成功率。

同一工作账本还使已有3×3 SVD 的真实秩二重建通过原预算（45601工作量、347节点）；99个有限样本单元与独立参考的最大绝对误差4.45e-16，另9个单元正确缺测。完整3×3重建与QR正规残差仍因原工作／节点上限拒绝，见 [矩阵分解边界](matrix-orthogonal.md)。
