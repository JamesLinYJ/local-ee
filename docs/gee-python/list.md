# GEE Python 兼容清单

状态：2026-10-22，第五批持续实施，整体兼容目标尚未完成。

第五批 [验证报告](../../reports/gee-python-wave5.json)：Linux Python **894 passed／7 skipped**，前端 **11 passed**、TypeScript 与构建通过；上一批为 [830 passed／7 skipped](../../reports/gee-python-wave4.json)，本批增加 64 项通过回归。7 项平台／配置跳过为 3 项 opt-in JVM/Spark 检查及 4 项 macOS Seatbelt 检查；它们不构成原生平台验收。

S＝官方客户端实际序列化；C＝本地编译；E＝实际栅格引擎；N＝独立数值基准；G＝Google 同数据对照。静态数值求值和合成图测试分别说明，不能标成原生栅格 E。固定的 991 项签名、方法可见数量和定向探针计数均不能换算为全 API 兼容百分比。

当前阶段按用户要求暂缓 Linux 隔离执行、macOS／ARM64 和本机真实数据验收，优先完成 Python API／参数／计算语义，再推进 JS。新增能力继续用版本化合成样本、独立数值参考及已有便携测试验证；延期项目不是本阶段前置条件，现有运行器与沙箱检查保留。

## 全量目录

[机器可读 Python API 清单](../../reports/gee-python-api-inventory.json) 包含 991 项固定算法签名、2,451 项算法参数、48 项公开 Python 类记录及 1,797 项 callable 签名记录，包括继承方法、参数种类／默认值、opt_* 别名、嵌套导出类和绑定来源。939 项算法找到了明确的 Python 命名绑定；其余 52 项标为未解析映射，仍可通过通用 ApiFunction 调用，不能据此判定后端不支持。

记录类型／方法存在和验证其计算行为是两件事；每项原始官方参数保留顺序、默认值和可选标志。公开云端 transport／OAuth 方法列入目录用于完整追踪，本地运行时仍禁用这些路径。生成器要求独立、未配置本地会话的 SDK 进程，避免本地适配替换方法后生成不完整目录。

## 已验证及待完成

- [x] SDK 1.7.49 固定版本、离线签名、共享编译器及既有 Python/openEO 链路。
- [x] 全 991 项算法签名及公开 Python 类型／方法／参数清单，独立进程重复生成一致。
- [x] Python 命名 GeoJSON CRS 字典解码，合法 filterBounds／clip／reduceRegion／表格几何编译；非法输入明确拒绝。
- [x] Filter.notNull 的缺失、null、0／False／空值、多属性、空列表和编译预算测试。
- [x] Dictionary 空 keys、缺键／非 null 默认值与 List.sequence count／step／端点语义回归。
- [x] 有限本地影像元数据 Join.simple／inverted／saveFirst／saveAll／saveBest，匹配保留真实影像、排序、outer 和后续像素图组合；唯一直接或 And 中的 maxDifference 提供数值时间差度量。
- [x] 有限静态 Array／矩阵构造、读取、变形、转置、乘法、逆、伪逆与满列秩线性求解；独立闭式数值参考。
- [x] 移除 SDK 初始化时绕过本地 transport 的 Google 弃用目录读取；初始化／重置及探针均有实际 Python 网络入口拦截回归。
- [x] 内联 FeatureCollection 的有界筛选、映射、排序、遍历、属性与列表操作；显式 ID 的 merge。
- [x] 内联表格 reduceColumns 的无权 linearFit／linearRegression，保留矩阵类型及每响应残差 RMS；闭式系数／残差参考与合成预测示例。
- [x] Number.format 的有界十进制子集，以及 String 数值构造、cat／length／compareTo 和分配前预算。
- [x] 唯一 maxDifference 与标量条件的 And 组合；最近前／后观测筛选、inner 匹配对和 Feature.map → ImageCollection 计算链路。
- [x] 有限静态 Array 的逐元素算术、slice／project／repeat／cat、单输出归约与累积、对称特征分解及 Cholesky；闭式 PCA 协方差、投影和重建验证。
- [x] 固定形状单数组波段的 Image.toArray、布局、矩阵乘法与单输出归约；静态 PCA 基投影到本地影像像素图，独立核对分量、重建和整体掩膜。
- [ ] 每一签名／参数组合的 S／C、适用的独立 N，以及负向、缺测、边界验收；E 按现有环境可用条件单独记录。
- [ ] 动态形状／多数组波段和其余 Image.array*、逐像元回归、分类训练／预测、矢量／空间和多重／歧义度量 Join、邻域及高级时序。
- [ ] 后续阶段：Linux 执行／隔离适配、macOS Seatbelt、ARM64 JNI 和本机真实数据验收；当前阶段延期。
- [ ] Google 同数据数值比较按可取得条件另记；本机真实完整项目验收延期。

既有本机 Python 地图、任务、GeoTIFF／CSV 和下载证据见 [Python 客户端报告](../../reports/gee-python-client.json)；本次 Linux 工作没有重新执行这些本机流程，也没有复制本机账号或影像。

## 本轮新增能力的准确边界

| 能力 | 本次证据 | 尚未覆盖 |
| --- | --- | --- |
| Python GeoJSON | S/C，命名 EPSG:4326 CRS、有限合法二维平面几何及非法输入 | 非 WGS84、球面边、left-inside、重投影容差；旧输入未写 geodesic 时延续既有平面策略，无 E/G |
| Filter.notNull | S/C，最多 1000 个平面属性名，共享 50000 步预算 | 嵌套属性选择器、Google 对照 |
| Dictionary／List | S/C；NumPy linspace／Python range 独立静态参考；空 keys 和缺键默认值回归 | 完整所有方法和类型强制转换；分数步长按生成 Float64 值比较端点，无 G |
| 有限 Join | S/C，simple／inverted／saveFirst／saveAll／saveBest／inner；maxDifference 可与标量条件作 And 组合；闭区间、最近前后观测和来源／掩膜参考 | <=1000 景；inner 最多 1000 匹配对，保留真实 Image 属性；请求度量时多重度量或 Or／Not 包含度量拒绝；空间／矢量、原生 E/G 未覆盖 |
| 静态 Array | S/C 与闭式独立 N；OLS 残差正交性、逆及秩一伪逆；工作预算拒绝 | <=8 轴／10000 单元、整数精确域 <=2^53；显式 PixelType／空构造／负下标拒绝；矩阵限二维，Solve 限满列秩方阵或超定；不含栅格 E/G |
| 固定形状栅格数组 | S/C；Image.toArray、arrayFlatten／Project／Transpose／Slice／Get／Length(s)／Reduce 和 matrixMultiply，同形 add／subtract／multiply／divide；独立合成图 N 验证来源、分量、重建及整体掩膜 | 单数组波段，<=8 轴／每轴 64／共 64 单元，非空维，共享 50000 工作步和 500 图节点；静态坐标、有限归约；Float32 callback 限制保留，动态形状／广播／直接数组栅格导出拒绝；无 E/G |
| 内联 FeatureCollection | S/C；size／first／toList／map／filter／limit／sort／merge／iterate／aggregate_array，属性保留有限 Array 和具体 Image；同类 Image 回调可接 ImageCollection 计算 | <=1000 要素，共享工作预算；Feature／Image 混合回调拒绝；merge 需要显式 ID 并加 1_／2_ 前缀；不含远程要素集或矢量引擎 |
| 表格回归 | S/C 与独立 N；linearFit、linearRegression，多响应系数／RMS；缺失／null 行跳过；秩不足／n<=numX 返回 null | <=1000 行、<=32 个平面属性列，共享预算；无权重；不支持栅格回归或 G |
| Number／String | S/C；%s／%d／%f、有限符号及填充；数值 String 构造与三个基础方法；指数拼接预算负控 | Number 按 Python 最短十进制拼写半入舍入，String 按 Python code point；科学／十六进制格式等拒绝；本地政策无 G |

List.contains／distinct 对嵌套数组使用显式的有界比较，避免 NumPy 隐式真值／广播错误。标量 int／float 按数值比较，bool 单独区分；Array 的 dtype／形状／元素比较仍是未做 Google 对照的本地策略。step 序列严格检查实际生成的 Float64 值，不向端点外扩展；例如 0、0.1、0.2 后的 0.30000000000000004 超过 end=0.3，因此省略，该舍入策略尚无 G 证据。

另有 21 项 Python／JS 固定 SDK 实际序列化后进入共享编译器的结果一致性回归，覆盖 count 序列、Dictionary、矩阵、notNull、Join（含 inner 和复合时间条件）、几何、表格回归、要素遍历、格式化及字符串构造；包括静态数组布局／归约、特征分解、Cholesky 和逐元素算术，以及两条实际栅格数组投影／归约计算图。这是保留共享后端行为的检查，不表示已完成 JavaScript 全量兼容。

第四批 `examples/10_GEE_python_synthetic_pca.py` 与 `tests/fixtures/ee-pca-table-v1.json` 串联有限静态表格的中心化、样本协方差、对称特征分解、投影及重建。四条二维观测的均值为 `[2,1]`，协方差为 `[[4/3,2/3],[2/3,2/3]]`，特征值为 `1±sqrt(5)/3`；闭式向量与得分按 1e-14 容差核对，重建还提供与符号选择无关的验证。S/C/N 已通过，网络入口尝试为 0；无栅格 E 或 G。

这批 Array 新增能力均受 10000 单元／每轴长度、8 轴及共享 50000 步预算限制。二元算术只接受同形数组，除零返回零，负数平方根和非有限结果拒绝。slice 接受负偏移和正步长，可产生空轴；project 仅接受升序不重复轴，删除轴长度必须恰为 1。repeat 拼接整个数组；cat 需要类型化 Array，尚不支持原始嵌套列表的强制转换。reduce 支持 sum／mean／min／max／count／median／sampleStdDev，归约轴保留长度 1；fieldAxis、多输出归约、空输入及少于两个值的样本标准差明确拒绝。accum 限 sum／min／max，浮点前缀按顺序相加；显式 PixelType 和完整广播仍待实现。

eigen 限非空二维实对称矩阵，Cholesky 另需正定，输出下三角 L；determinant 限方阵，trace／diagonal 支持矩形。eigen 按特征值降序输出行向量，每行首个最大绝对值分量取正；重根子空间沿用 LAPACK 基。该符号／重根呈现规则是尚无 Google／EJML 对照的本地政策。浮点 sum／mean／median／trace 对有限抵消使用稳定求和，必要时在有界二进制有理数域完成中间求和，避免可表示结果因中间溢出而失败；这不代表所有浮点内核具有相同的极值稳定性。

第五批 `examples/11_GEE_python_synthetic_raster_projection.py` 与 `tests/fixtures/ee-raster-projection-v1.json` 使用同一合成训练表求 PCA 基，将本地 red／nir 像素中心化、转列数组、矩阵投影并重建波段。数值参考使用闭式正交基，任一输入波段缺失时所有分量／重建波段均无效；输入来源、顺序和显式复制的时间／ID 属性也有回归。S/C/N 已通过、网络入口尝试为 0；N 使用独立测试图求值器，实际栅格引擎 E 与 Google G 未运行。

栅格数组在编译器内部保持独立类型，只有 arrayFlatten／arrayGet／arrayLength 等标量输出进入既有后端；不将单元伪装成公开影像波段。数组常量的波段名为 constant，普通 scalar Image.toArray 输出 array；已有数组再次 toArray 保留原名，此命名政策尚无 G 对照。固定形状的 arrayReduce 支持 sum／mean／min／max／count／median／sampleStdDev；fieldAxis、多输入输出归约及单元素样本标准差拒绝。arrayProject 仅支持升序保留轴、删除轴长度恰为 1；slice/get 仅支持数值或所列纯算术常量 Image 坐标，动态／掩膜坐标拒绝，slice 产生空轴时拒绝。rank0 可经空坐标 arrayGet 取值，rank0 flatten／arrayLengths 仍拒绝。

静态 If 分支、Dictionary 缺键默认值和 Image 显式转换均保留数组影像类型；重命名、属性设置／读取／复制仍针对逻辑单波段。未支持的影像算子遇到数组类型时明确失败，类型不能泄漏为 JSON 或被当作静态真值。ImageCollection.toArray、动态数组形状、多数组波段、广播、逐像元特征分解及直接数组影像导出仍待实现。

版本化样本 `tests/fixtures/ee-table-workflow-v1.json` 和可运行示例 `examples/08_GEE_python_synthetic_regression.py` 串联有效值筛选、表格 OLS、矩阵预测和格式化。手算系数为 0.5／2.5、残差 RMS 为 sqrt(0.5)、第 3 日预测为 8。它是静态合成表格工作流，不是实际影像、栅格 E 或 Google 对照。

第三批的 `tests/fixtures/ee-temporal-interpolation-v1.json` 与 `examples/09_GEE_python_temporal_interpolation.py` 串联最近前／后观测、毫秒权重及像素插值；合成信号的手算输出为 `[6, masked, masked]`，保留目标时间及两个邻居的有效像素交集。inner 匹配后组合两个来源的波段也有独立来源／掩膜参考。示例函数需要调用方提供实际本地集合，测试使用明确版本化的合成目录／数组；本轮尚未运行实际栅格引擎。

度量 Join 仅在请求 measureKey／saveBest 时要求恰好一个 maxDifference，且它只能直接出现或位于 And 下。其余标量逻辑可组合；不请求度量的布尔 Or／Not／多条件保留原有筛选行为。inner 的 measureKey 位于匹配对 Feature 上，saveFirst／saveAll／saveBest 的 measureKey 位于匹配 Image 上；默认 inner 键为 primary／secondary，自定义键必须互异，避免覆盖匹配来源。

内联要素的有序属性比较将缺失／null 视为 UNKNOWN；Not 保留 UNKNOWN，And／Or 使用三值逻辑，最终 UNKNOWN 不匹配。这能保留 SDK 的 gte／lte → Not(lt／gt) 序列化语义；该空值政策尚无 Google 对照。涉及缺失／null 的 equality 及复杂对象比较明确拒绝，不能据此宣称完整 Filter 兼容。递归谓词、成员扫描和字符串比较共享编译预算。

整个公开输出共享对象数、深度和 1 MB 编码预算，字符串转义和重复匹配属性在转换期间计费，避免先分配巨大 JSON 再拒绝。静态数组和匹配影像在编译器内部保留类型，到公开边界才转换为有限 JSON；不公开 Pixel IR 或磁盘路径。

## 当前 Python 调用探针

来源：`tests/fixtures/ee-python-1.7.49.json`，v2。原有 50 项调用保持不变，50 项 S、45 项 C 通过、5 项 C 明确拒绝；交接基线为 38／12。每行 E／N／G 均标为未运行，独立静态数值与合成图证据来自上述专用测试。导出行只验证表达式和本地选项准备，不能据此声明导出执行成功。

网络守卫拦截并计数本地 transport、Python socket 连接／发送和 DNS 入口，当前观察到 0 次尝试；该证据不是内核抓包或任意用户程序的隔离证明。

| 调用 | S | C | 当前输出或拒绝原因 |
| --- | --- | --- | --- |
| `number_add` | passed | passed | 9 |
| `number_divide_format` | passed | passed | "3.50" |
| `date_get_year` | passed | passed | 2023 |
| `date_difference_days` | passed | passed | 1.0 |
| `date_advance` | passed | passed | "2023-11-16T00:00:00.000+00:00" |
| `list_map_lambda` | passed | passed | [2,4,6] |
| `list_iterate_lambda` | passed | passed | 6 |
| `dictionary_get` | passed | passed | 4 |
| `conditional` | passed | passed | "yes" |
| `geometry_rectangle` | passed | passed | {"coordinates":[[[100.1,30.1],[100.9,30.1],[100.9,30.9],[100.1,30.9],[100.1,30.1]]],"type":"Polygon"} |
| `collection_load` | passed | passed | blue, green, red, nir, SCL |
| `filter_date` | passed | passed | blue, green, red, nir, SCL |
| `filter_bounds` | passed | passed | blue, green, red, nir, SCL |
| `filter_metadata` | passed | passed | blue, green, red, nir, SCL |
| `filter_and_sort` | passed | passed | blue, green, red, nir, SCL |
| `select_named_bands` | passed | passed | NIR, RED |
| `map_ndvi_copy_properties` | passed | passed | NDVI |
| `expression_ndvi` | passed | passed | NDVI |
| `addbands_constant_named` | passed | passed | red, constant |
| `update_mask` | passed | passed | blue, green, red, nir, SCL |
| `unmask_fill` | passed | rejected | Image.unmask sameFootprint=false with a global footprint is not supported |
| `where_threshold` | passed | passed | nir |
| `clip_region` | passed | passed | blue, green, red, nir, SCL |
| `reduce_region_named` | passed | passed | blue, green, red, nir, SCL |
| `collection_mean` | passed | passed | blue, green, red, nir, SCL |
| `collection_median` | passed | passed | blue, green, red, nir, SCL |
| `collection_max` | passed | passed | blue, green, red, nir, SCL |
| `collection_mosaic` | passed | passed | blue, green, red, nir, SCL |
| `quality_mosaic` | passed | passed | blue, green, red, nir, SCL |
| `collection_count` | passed | passed | blue, green, red, nir, SCL |
| `collection_to_bands` | passed | passed | scene-a_nir, scene-b_nir, scene-c_nir |
| `collection_from_images` | passed | passed | blue, green, red, nir, SCL |
| `collection_limit_sort` | passed | passed | blue, green, red, nir, SCL |
| `map_copy_system_properties` | passed | passed | blue, green, red, nir, SCL |
| `map_set_dynamic_property` | passed | passed | blue, green, red, nir, SCL |
| `map_arithmetic_rename` | passed | passed | reflectance |
| `first_dynamic_property` | passed | passed | "scene-a" |
| `aggregate_array_properties` | passed | passed | ["scene-a","scene-b","scene-c"] |
| `filter_date_algorithm` | passed | passed | blue, green, red, nir, SCL |
| `map_expression` | passed | passed | difference |
| `image_band_names` | passed | passed | ["blue","green","red","nir","SCL"] |
| `image_to_float` | passed | passed | nir |
| `neighborhood_reduce_kernel` | passed | rejected | Unsupported Earth Engine algorithm: Kernel.square |
| `focal_mean` | passed | rejected | Unsupported Earth Engine algorithm: Image.focalMean |
| `join_save_first` | passed | passed | blue, green, red, nir, SCL |
| `array_matrix_multiply` | passed | passed | [[3],[7]] |
| `regression_reducer` | passed | rejected | This regression Reducer currently supports static table reduceColumns only |
| `classifier_constructor` | passed | rejected | Unsupported Earth Engine algorithm: Classifier.smileRandomForest |
| `export_image_drive` | passed | passed | NIR |
| `export_table_drive` | passed | passed | {"features":[{"geometry":{"coordinates":[[[100.1,30.1],[100.9,30.1],[100.9,30.9],[100.1,30.9],[100.1,30.1]]],"type":"Polygon"},"properties":{"mean":3,"scene"... |

## 复现与后续顺序

```sh
.venv/bin/python -m scripts.ee_python_inventory
.venv/bin/python -m scripts.ee_python_probes --check
.venv/bin/python -m pytest -q
npm --prefix web test
.venv/bin/python scripts/build_web.py
```

继续按真实 Python 项目依赖补全栅格数组、逐像元回归，然后采样／分类训练预测、矢量／空间 Join、邻域／高级时序；优先使用版本化合成样本验证计算语义，本阶段不推进 Linux 隔离适配或要求原生／真实数据验收。当前剩余的 5 项定向拒绝是全局 footprint unmask、Kernel.square／邻域、focalMean、栅格 linearRegression 和 smileRandomForest；它们只是已探测缺口，不是剩余功能的完整清单。

[GOAL.md](../../GOAL.md) 记录持续目标；[云端交接](../cloud-handoff.md) 保留环境和发布约束。Python 达标后再系统推进 JS，期间共享后端改动持续回归已有 JS 功能。
