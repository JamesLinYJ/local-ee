# 要素元数据与几何整理

本页说明 Wave56 的固定合成工作流。Python 和 JavaScript 示例使用各自固定版本的官方客户端构造相同表达式，再由本地有界编译器处理；输入仅来自 [feature preparation v1 夹具](../../tests/fixtures/ee-feature-preparation-wave56-v1.json) 和元数据合成目录。它不读取栅格文件，不请求 Google，也不需要用户账号。

## 站点要素

[Python 示例](../../examples/61_GEE_python_feature_preparation.py) 与 [JavaScript 示例](../../examples/javascript/15_要素数据整理.js) 从相同的十二条固定站点记录开始。复合属性条件按 `station_code` 前缀 `CN-`、后缀 `-QA`、`reading` 闭区间 `[5, 12]` 和 `system:time_start` 的 UTC 年积日闭区间 `[91, 120]` 筛选。随后按固定矩形执行空间筛选。独立预期清单保留五个符合属性条件的 ID，其中一个为空几何、一个在矩形外；空间筛选后留下三个 ID。

映射回调以字面字段名 `station_code` 和锚定正则 `^station_name$` 选取两个字段，将它们重命名为 `site_code` 和 `station_name`；质量标记由 typed string getter 读取后加入结果。`Feature.id()` 读取明确设置的 `system:index`，输出继续保留原 ID（作为 Feature 的独立 ID，而非被选择的属性）。示例还用 `getNumber` 和 `getArray` 读取有类型约束的属性，用 `toArray` 按字段顺序形成 `[reading, height_m]`，并以 `toDictionary` 选择原始字段。缺失或显式 null 的 typed getter 返回 null；`toDictionary` 对显式列表中的缺失键省略该键。示例通过 `Geometry.type()` 和 `coordinates()` 保存输入几何信息，再用声明的经纬度建立 WGS84 点并调用 `setGeometry`。单独的 null-geometry 控制验证未被替换的空几何仍为空。

类型错误的显式静态属性、错误的字段选择/重命名参数会在编译中拒绝。缺失或 null 的读数不会通过读取数值字段的范围条件；包含空几何的 Feature 在空间筛选时不匹配。空集合没有可供回调读取的行，因此不会模拟缺字段或错误属性类型的运行时失败；但无效的静态回调参数仍在空集合结果产生前拒绝。

## 常用写法

下面都是 Python 官方客户端写法，JavaScript 对应方法见配套示例。表中的结果是当前本地实现范围；不能据此推断所有动态表或参数已支持。

| 写法 | 结果与限制 |
| --- | --- |
| `feature.getNumber("reading")` / `getString("quality")` | 有限数值／字符串；缺失和 null 返回 null，其他类型明确拒绝 |
| `feature.getArray("samples")` | 属性必须由 `ee.Array(...)` 创建；普通列表不会自动转换 |
| `feature.toDictionary(["station_code", "reading"])` | 保留指定实际键；省略列表时只选非 `system:*` 属性，缺键省略是本地政策 |
| `feature.select(["station_code", "^station_name$"], ["code", "name"])` | 有序选择和重命名；普通字段名也经过 RE2 校验，复杂模式保留完整扫描预算 |
| `feature.id()` / `feature.setGeometry(point)` | 读取实际 ID／替换为有界平面几何；`setGeometry(None)` 清空几何 |
| `feature.toArray(["reading", "height_m"])` | 按顺序生成一维数值数组；缺失、null、布尔及非数值字段拒绝 |
| `point.type()` / `coordinates()` / `geometries()` | 类型、坐标或直接子几何；单个几何的 `geometries()` 返回单元素列表 |
| `ee.Filter.stringStartsWith("station_code", "CN-")` / `stringEndsWith(...)` | 实际字符串前后缀判断，支持有限目录、内联及取样／分类结果表 |
| `ee.Filter.rangeContains("reading", 5, 12)` / `dayOfYear(91, 120)` | 闭区间；年积日使用 UTC，取样／分类结果表暂不支持日期筛选 |

`Element.replaceProperties` 是固定算法表中的隐藏入口，Python 类没有同名绑定，可通过 `ee.ApiFunction.call_("Element.replaceProperties", destination=feature, source=other)` 调用。它替换属性；省略／null 来源清除普通属性。本地实现保留目标的实际身份：要素移到顶层 `id`，影像保留已有 `system:index` 并关闭原属性继承；来源的冲突索引会拒绝。这些身份和缺键政策没有 Google 同数据对照。

几何只接收有限 EPSG:4326 平面值。显式球面边、投影坐标、非空重投影容差及 `evenOdd=false` 仍拒绝；省略边类型沿用本地平面政策。`Geometry.projection` 与 `Filter.hasType` 尚未支持。

## 影像目录元数据

第二个小工作流对本地 `sentinel-2-l2a` 合成目录按 ID 前后缀、云量闭区间、年积日和矩形过滤，随后用 `getNumber` 与 `getString` 读取云量和场景 ID。这里验证的是固定目录项元数据；没有像素运算，也不代表目录中的真实 Sentinel-2 数据或 Google 集合行为。

## 验证与边界

`tests/test_ee_feature_preparation_workflow.py` 用两种客户端编译 Python／JavaScript 表达式，并将结果与夹具中逐行写定的期望比较。分数另用 `Fraction` 从输入读数和高程独立计算，不以编译器输出来生成期望值。测试还将编译后的三个站点交给既有本地表格 dispatch、worker 和结果读取路径，检查物理 CSV 的全部行、列、数组、字典、ID 与替换几何，并记录 CSV SHA-256。该测试不启动 HTTP 服务、不访问 Google 或用户账户，也不验证完整 Spark、原生沙箱、浏览器、部署或生产验收。

编译及该固定 CSV 读回只证明夹具覆盖的有限路径。一个先前尝试用 8 个选择器处理 3 行记录的组合超过了共享 50,000 字符串工作预算；当前示例验证一个字面字段选择器加一个锚定正则、共选两个字段，不说明原组合或所有最大规模操作可以一起运行。字段、类型、空值和几何检查不是对所有动态集合行的预验证；最大规模仍受现有表达式、表格和工作预算约束。空集合上的类型相关验证只适用于能从静态参数本身判定的错误。
