# GEE API 兼容清单与证据边界

本页配合 [完整机器可读清单](../reports/gee-api-inventory.json) 使用。清单固定于官方 `@google/earthengine` **1.7.49**、提交 `e189e4b89e785019ea5642ea8e80cb644749cd4a`。当前源文件含 **991 个唯一算法签名、2,451 个参数项**；当前同名处理器声明数量见生成报告。这些记录分别描述上游目录、参数和本地声明，不表示兼容率。

Python 类型、方法、继承方法、参数默认值和命名绑定另见 [Python API 报告](../reports/gee-python-api-inventory.json) 与 [Python 优先清单](gee-python/list.md)。2026-10-22 新增的有限 metadata Join 和静态 Array／矩阵支持，不表示 Image.array*、栅格回归或整个公开工作流已经完成。旧审计计数继续作为历史上下文保留。

第三十三批历史按五个静态算子族新增98个实际计算入口，当批同名处理器声明 **377／991（38.04%）**。包括官方目录单列别名，只统计名称，不能作为完整参数、运行时、数值或迁移成功率。分组语法、局部政策和证据见 [Python当前清单](gee-python/list.md)、[批量合同](gee-python/static-families.md) 与 [验证报告](../reports/gee-python-wave33.json)。

第三十四批当前名称入口 **416／991（41.98%）**，新增39个名称（含12个官方单列别名），其中16种Image科学函数经过实际瓦片计算验证。完整参数、网格／精度和Google行为仍有边界；参见[影像数学合同](gee-python/pixel-math.md)与[报告](../reports/gee-python-wave34.json)。

## 清单范围

JSON 为每一个 `vendor/earthengine-js/algorithms.json` 条目保留官方算法名、返回类型、描述及原始有序参数记录，包括可选标志和默认值。名称、签名和参数完整性由测试与 pinned 文件逐项比较。每个条目也包含：

- 本地编译器是否在 `SUPPORTED_FUNCTIONS` 中声明了同名处理器；
- 该调用名是否出现在定向 SDK 序列化表达式中，以及它共现的整图编译通过/拒绝数量；
- 已经明确的局部参数或语义限制；
- 对单独运行、独立数值等价和 Google 同数据比较的逐方法状态。

处理器声明只代表源码中的调度清单。它不代表完整参数支持、可在引擎中执行或与 GEE 数值相同。名字未出现在同名处理器清单，也只说明没有同名声明；不能仅从这一点认定 API 一定不支持。每项 API 的 `argument_coverage_complete` 都设为 `false`，已知局限单独列出；没有列入局限清单不表示实现完整。

## S/C/E/N/G 分层

| 层级 | 清单含义 | 不代表 |
|---|---|---|
| S 签名 | 固定官方 SDK 清单含该算法和参数 | 本地有对应计算 |
| S 探针 | 所选表达式中，官方 SDK 成功序列化了该调用名 | 全量语法、重载或参数值都已验证 |
| C 声明 | 本地 `SUPPORTED_FUNCTIONS` 中有同名条目 | 所有参数和语义均已实现 |
| C 共现 | 某个包含该名字的整图编译通过或拒绝 | 该 API 的独立正反测试；整图可能由其他节点触发结果 |
| E | 尚未对每条签名逐项证明实际引擎运行 | 不能由静态声明或编译通过代替 |
| N | 只记录单独列出的本地数值基准样例 | 不推导到样例中的所有 API 或参数 |
| G | 当前没有 GEE 同数据服务端比较 | 不声称 Google Earth Engine 数值等价 |

因此，清单**不计算 API 支持百分比**。现有复杂兼容审计是基于已知工作流的定向选择，不是随机 API 抽样；嵌套表达式可能在到达目标节点前即被拒绝。

## SDK 辅助方法与实际序列化名

有些常用的 GEE JavaScript 方法由客户端先转换为别的 API 调用，并没有独立的服务器算法签名。机器清单的 `selected_client_helper_lowerings` 记录经固定客户端源码确认的代表性降级关系，例如：

| JavaScript 写法 | 官方客户端构造的调用 |
|---|---|
| `ee.Filter.inList(...)` | `Filter.listContains`，并重排 field/value 参数 |
| `ee.Filter.eq/neq/lt/gte/gt/lte(...)` | `Filter.equals`、`Filter.lessThan` 或 `Filter.greaterThan`，必要时再加 `Filter.not` |
| `ee.Filter.date(...)`、`collection.filterDate(...)` | `DateRange`、`Filter.dateRangeContains`，以及 `Collection.filter` |
| `collection.filterBounds(...)` | `Feature`、`Filter.intersects`、`Collection.filter` |
| `collection.sort(...)` | `Collection.limit`；属性排序通过未定义的 max 参数表达 |
| `imageCollection.select(...)` | `Collection.map` 与 `Image.select` |
| `ee.Image.cat(...)`、`ee.Image.rgb(...)` | `Image.constant`、`Image.addBands`，以及可选的 `Image.select` |

这也是为什么只搜索编译器中的方法名容易误判兼容状态。任何新增适配都应先检查固定版客户端实际序列化的表达式。

## 复杂工作流的优先缺口

公开复杂样例检查覆盖云与阴影处理、谐波时序、分类、矩阵回归、HISTARFM 插值和 LandTrendr。下表列出已保存的源审查中发现的主要缺口。源审查早于部分近期实现；JSON 会另行标记当前源码是否已有同名 handler 声明，但声明仍未证明参数及语义已验证。

| 工作流 | 主要计算或运行时缺口 |
|---|---|
| Sentinel-2 云影处理 | 有限影像元数据 `Join.saveFirst` 已补；完整云概率数据配准、投影/重投影、定向距离变换、`focalMin` / `focalMax` 仍缺，不能把本地有限别名视为完整数据镜像 |
| 谐波时序 | 已补有限逐景日期、定长集合数组、布局、静态设计矩阵求解、受限回归和合成谐波拟合／振幅；静态 Number／Array.atan2 采用 SDK 轴政策，Image.atan2 相位、变长数组、通用动态设计和所需 Landsat 数据仍有缺口；没有 Google 同数据对照 |
| 随机森林分类 | 有限标签混淆矩阵、总体指标与静态最小距离模型已补；遥感样本提取、随机森林训练／栅格预测及完整批量区域统计仍缺 |
| 矩阵 OLS | 已补有限静态矩阵、定长逐波段集合数组、固定形状布局与静态设计的 Image.matrixSolve；有效行压缩、动态设计及完整 Float64 栅格矩阵计算仍缺 |
| HISTARFM 插值 | `Date.difference` / `getRelative` 有限 UTC 标量实现不能覆盖所有时间 Join 场景；独立常量栅格与完整投影语义、`int16`、时间 Join 与匹配列表属性仍是主要缺口 |
| LandTrendr | 用户模块解析、高级时序分段、数组/像元连通语义与 Image QA 位运算 |

定向检查中，50 个表达式由固定 SDK 序列化；3 个正向编译对照通过、43 个因算子或语义被拒绝、4 个因数据或波段被拒绝。这是表达式级观察，不能当作算法覆盖比。另有 14 个图规模编译点，场景数包括 1、10、20、30、50、100 和 365；它们只测图规模，不测吞吐或端到端长时序运行。已观察到双波段均值 30 景生成 335 节点、50 景超过现有 500 节点限制。

近期已加入 `ImageCollection.qualityMosaic` 的局部编译路径，以及 `Date.difference`、`Date.getRelative`、`Date.getFraction` 的有限标量日期路径。`qualityMosaic` 要求集合非空、每景具有同名质量波段，并且波段名和顺序完全相同；无效质量像元会被排除，胜出影像的载荷掩膜会保留，相同质量值目前选择集合中最后一景，尚未与 Google 服务对照。日期运算只接受可解析的本地毫秒标量，日历年份范围为 1..9999，时区仅 UTC；`Date.difference` 的年/月使用平均时长常数作为本地策略，ISO 周规则和这些边界均没有 Google 数值对照。`getRelative` 的 week-in-month、相同 unit 和未列明日历组合明确拒绝。`Collection.map(dropNulls=true)` 对有元数据依赖的映射进行有限逐景求值，仍受 1,000 景限制。这些是局部路径和限制说明，不是端到端复杂工作流验收。

当前还声明了七个 `Number` 标量位运算方法：`bitCount`、`bitwiseNot`、`bitwiseAnd/Or/Xor`、`leftShift` 和 `rightShift`。它们只处理已解析的静态标量整数，不代表对应 `Image.*` 栅格算法可用；二进制 AND/OR/XOR 只接受非负输入，左移限于无溢出的有符号 64 位范围，其他不确定的 coercion/溢出会显式拒绝。`Image.toFloat` 和 `Image.toDouble` 通过本地类型转换适配器处理栅格；Float64 的一般像元回调运算仍被拒绝，但有界原生时间归约支持 `mean`、`median`、`min`、`max`、`sum`、`count`、`first`、`last` 和样本标准差。此有界归约也适用于 `Image.unmask` 的 Float64 结果；该调用仍要求掩膜替换网格对齐且观测时刻相同，默认保留输入 footprint，`sameFootprint=false`、隐式重投影和跨时刻广播仍拒绝。上述路径没有 Google 同数据数值对照。

`Image.constant` 和 `Image.addBands` 支持一个有限子集：有限数值标量及已支持的静态标量算术可以绑定到有真实本地栅格来源的目标影像，包括 `addBands(ee.Image.constant(...))` 和逐景的 `ee.Image(image.date().millis())`。新增常量在目标本地网格和 footprint 内独立有效，不继承目标波段的像元掩膜；之后可用上述有界 Float64 时间归约。常量绝对值及运算结果限制在精确 Float64 范围 `<= 2^53`。独立/global 常量栅格、投影查询、跨网格或隐式时间广播、数组常量、任意类型提升和精确 Google 边界网格等价仍不支持或未验证。14 个官方 SDK 常量/日期表达式的原生验收共输出 18 个波段，掩膜、波段顺序和数值均与独立基准一致；这项样例不代表所有 `Image.constant` / `addBands` 重载均已实现。

## 运行时交互也属于迁移范围

GEE Code Editor 的全局环境不仅是 `ee.*` 算法：地图、导出、`ui.Chart` / `ui.Panel` 和 `require('users/...')` 也是实际脚本的一部分。当前本地 runner 有 `print`、有限的 `Map`、本地 `Export.image.toDrive` 和 `Export.table.toDrive` 适配；Cloud Storage / EE Assets 导出明确不可用。现有隔离运行探针显示 `ui` 命名空间和远程用户模块不可用。不得把算法清单误认为 Code Editor 全局 API 清单。

## 数值证据的实际边界

当前有一份真实本地预处理 Sentinel-2 NDVI 样例与独立 Rasterio/NumPy 栅格基准比较：45,590 个有效像元、掩膜不匹配 0、最大绝对误差 0，容差 `1e-6`。另有三景合成的 23 项多波段时序归约夹具与独立 NumPy 基准比较通过，掩膜不匹配 0、最大绝对误差 0。这些证明特定数据、网格与表达式的结果，**不证明每个 API 签名、参数、全局 GEE 服务或 Google 同数据等价**。清单将这些结果放在全局上下文里，不错误地贴到每个算法上。

## 再生成与检查

在仓库根目录运行：

```sh
python3 scripts/ee_capability_inventory.py
python3 -m pytest tests/test_ee_capability_inventory.py
```

默认生成器只读取 pinned 签名、编译器的静态 handler 声明，以及仓库中可审查的脱敏证据快照 `reports/gee-evidence-snapshot.json`；它不依赖本机 `audit/` 目录，因此可在干净克隆和 CI 中运行。不联网、不执行 JS/Python 用户脚本、不启动服务。快照和报告不会复制原始审计 JSON、运行错误文本、机器绝对路径、作业标识或凭据。测试验证签名及参数一一对应、处理器声明映射、快照 schema、无 `audit/` 的隔离检出生成、隐私字段排除和重复生成字节级确定性。

若本机有更新后的 allowlisted 审计材料，可显式运行 `python3 scripts/ee_capability_inventory.py --refresh-local-evidence`，该命令会从审计目录抽取固定字段并重写脱敏快照，再生成报告。提交前应逐项审阅快照 diff；不要提交原始或忽略的审计目录。更新 pinned SDK 时也要同步版本锁和快照的 SDK 版本，再生成并检查清单。
