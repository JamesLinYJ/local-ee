# GEE Python 兼容清单

状态：2026-10-21，第二批持续实施，整体兼容目标尚未完成。

第二批 [验证报告](../../reports/gee-python-wave2.json)：Linux Python **709 passed／7 skipped**，前端 **11 passed**、TypeScript 与构建通过；上一批为 [597 passed／7 skipped](../../reports/gee-python-wave1.json)，本批增加 112 项通过回归。7 项平台／配置跳过为 3 项 opt-in JVM/Spark 检查及 4 项 macOS Seatbelt 检查；它们不构成原生平台验收。

S＝官方客户端实际序列化；C＝本地编译；E＝实际栅格引擎；N＝独立数值基准；G＝Google 同数据对照。静态数值求值和合成图测试分别说明，不能标成原生栅格 E。固定的 991 项签名、方法可见数量和定向探针计数均不能换算为全 API 兼容百分比。

## 全量目录

[机器可读 Python API 清单](../../reports/gee-python-api-inventory.json) 包含 991 项固定算法签名、2,451 项算法参数、48 项公开 Python 类记录及 1,797 项 callable 签名记录，包括继承方法、参数种类／默认值、opt_* 别名、嵌套导出类和绑定来源。939 项算法找到了明确的 Python 命名绑定；其余 52 项标为未解析映射，仍可通过通用 ApiFunction 调用，不能据此判定后端不支持。

记录类型／方法存在和验证其计算行为是两件事；每项原始官方参数保留顺序、默认值和可选标志。公开云端 transport／OAuth 方法列入目录用于完整追踪，本地运行时仍禁用这些路径。生成器要求独立、未配置本地会话的 SDK 进程，避免本地适配替换方法后生成不完整目录。

## 已验证及待完成

- [x] SDK 1.7.49 固定版本、离线签名、共享编译器及既有 Python/openEO 链路。
- [x] 全 991 项算法签名及公开 Python 类型／方法／参数清单，独立进程重复生成一致。
- [x] Python 命名 GeoJSON CRS 字典解码，合法 filterBounds／clip／reduceRegion／表格几何编译；非法输入明确拒绝。
- [x] Filter.notNull 的缺失、null、0／False／空值、多属性、空列表和编译预算测试。
- [x] Dictionary 空 keys、缺键／非 null 默认值与 List.sequence count／step／端点语义回归。
- [x] 有限本地影像元数据 Join.simple／inverted／saveFirst／saveAll／saveBest，匹配保留真实影像、排序、outer 和后续像素图组合；直接 maxDifference 提供数值时间差度量。
- [x] 有限静态 Array／矩阵构造、读取、变形、转置、乘法、逆、伪逆与满列秩线性求解；独立闭式数值参考。
- [x] 移除 SDK 初始化时绕过本地 transport 的 Google 弃用目录读取；初始化／重置及探针均有实际 Python 网络入口拦截回归。
- [x] 内联 FeatureCollection 的有界筛选、映射、排序、遍历、属性与列表操作；显式 ID 的 merge。
- [x] 内联表格 reduceColumns 的无权 linearFit／linearRegression，保留矩阵类型及每响应残差 RMS；闭式系数／残差参考与合成预测示例。
- [x] Number.format 的有界十进制子集，以及 String 数值构造、cat／length／compareTo 和分配前预算。
- [ ] 每一签名／参数组合的完整 S／C／E／N 及负向、缺测、边界验收。
- [ ] Image.array*、逐像元回归、分类训练／预测、矢量／空间和复合度量 Join、邻域及高级时序。
- [ ] Linux 完整执行隔离和引擎验收；保留 macOS Seatbelt、ARM64 JNI 和真实数据验收。
- [ ] Google 同数据数值比较与真实完整项目验收。

既有本机 Python 地图、任务、GeoTIFF／CSV 和下载证据见 [Python 客户端报告](../../reports/gee-python-client.json)；本次 Linux 工作没有重新执行这些本机流程，也没有复制本机账号或影像。

## 本轮新增能力的准确边界

| 能力 | 本次证据 | 尚未覆盖 |
| --- | --- | --- |
| Python GeoJSON | S/C，命名 EPSG:4326 CRS、有限合法二维平面几何及非法输入 | 非 WGS84、球面边、left-inside、重投影容差；旧输入未写 geodesic 时延续既有平面策略，无 E/G |
| Filter.notNull | S/C，最多 1000 个平面属性名，共享 50000 步预算 | 嵌套属性选择器、Google 对照 |
| Dictionary／List | S/C；NumPy linspace／Python range 独立静态参考；空 keys 和缺键默认值回归 | 完整所有方法和类型强制转换；分数步长按生成 Float64 值比较端点，无 G |
| 有限 Join | S/C，simple／inverted／saveFirst／saveAll／saveBest；数值 maxDifference 闭区间和最小度量参考；来源、掩膜及后续像素图组合 | <=1000 景；flat 有限标量比较；本地稳定顺序和平分；空间／矢量／复合度量、inner、原生 E/G |
| 静态 Array | S/C 与闭式独立 N；OLS 残差正交性、逆及秩一伪逆；工作预算拒绝 | <=8 轴／10000 单元、整数精确域 <=2^53；显式 PixelType／空构造／负下标拒绝；矩阵限二维，Solve 限满列秩方阵或超定；不含栅格 E/G |
| 内联 FeatureCollection | S/C；size／first／toList／map／filter／limit／sort／merge／iterate／aggregate_array，属性不可变及回调组合 | <=1000 要素，共享工作预算；merge 需要显式 ID 并加 1_／2_ 前缀；不含远程要素集或矢量引擎 |
| 表格回归 | S/C 与独立 N；linearFit、linearRegression，多响应系数／RMS；缺失／null 行跳过；秩不足／n<=numX 返回 null | <=1000 行、<=32 个平面属性列，共享预算；无权重；不支持栅格回归或 G |
| Number／String | S/C；%s／%d／%f、有限符号及填充；数值 String 构造与三个基础方法；指数拼接预算负控 | Number 按 Python 最短十进制拼写半入舍入，String 按 Python code point；科学／十六进制格式等拒绝；本地政策无 G |

List.contains／distinct 对嵌套数组使用显式的有界比较，避免 NumPy 隐式真值／广播错误。标量 int／float 按数值比较，bool 单独区分；Array 的 dtype／形状／元素比较仍是未做 Google 对照的本地策略。step 序列严格检查实际生成的 Float64 值，不向端点外扩展；例如 0、0.1、0.2 后的 0.30000000000000004 超过 end=0.3，因此省略，该舍入策略尚无 G 证据。

另有 13 项 Python／JS 固定 SDK 实际序列化后进入共享编译器的结果一致性回归，覆盖 count 序列、Dictionary、矩阵、notNull、Join、几何、表格回归、要素遍历、格式化及字符串构造；这是保留共享后端行为的检查，不表示已完成 JavaScript 全量兼容。

版本化样本 `tests/fixtures/ee-table-workflow-v1.json` 和可运行示例 `examples/08_GEE_python_synthetic_regression.py` 串联有效值筛选、表格 OLS、矩阵预测和格式化。手算系数为 0.5／2.5、残差 RMS 为 sqrt(0.5)、第 3 日预测为 8。它是静态合成表格工作流，不是实际影像、栅格 E 或 Google 对照。

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

继续按真实 Python 项目依赖实现矢量／复合度量 Join、Image.array* 与栅格线性回归，然后采样／分类训练预测、邻域／高级时序；同时独立推进 Linux 隔离执行与引擎验收。当前剩余的 5 项定向拒绝是全局 footprint unmask、Kernel.square／邻域、focalMean、栅格 linearRegression 和 smileRandomForest；它们只是已探测缺口，不是剩余功能的完整清单。

[GOAL.md](../../GOAL.md) 记录持续目标；[云端交接](../cloud-handoff.md) 保留环境和发布约束。Python 达标后再系统推进 JS，期间共享后端改动持续回归已有 JS 功能。
