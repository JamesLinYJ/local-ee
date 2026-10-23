# GEE 兼容目标（Python 优先）

更新日期：2026-10-23。状态：进行中。用户要求：先尽量完整兼容固定版本 GEE Python API、参数及计算语义，再完善 GEE JavaScript；持续实际修改代码、运行测试并保存证据。

## 目标

首要目标是在离线签名和本地后端上逐项实现 `earthengine-api` 1.7.49 的类型、方法、参数、错误和计算语义，使真实 Python 遥感工作流能够在本地正确运行。以固定的 991 项算法签名及 Python 类型／方法／参数清单追踪进度，不以方法可见、客户端序列化或 handler 注册代替后端实现。

先按 `docs/gee-python/list.md` 修复 Python 合法几何／投影输入、Filter.notNull、Dictionary 和 List.sequence，再推进 Join、数组矩阵、回归、分类及真实工作流。共享编译器每批同时回归已有 JS、Python/openEO、地图、导出、认证和数据管理。Python 优先目标达标后，再系统完成固定版本 JavaScript API 及 Code Editor 的地图、图表、模块交互。

按用户 2026-10-22 的阶段调整，当前集中完成 Python API、参数及计算语义兼容，随后推进 JavaScript。Linux 隔离执行适配、macOS／ARM64 原生验收和本机真实影像验收延期，不作为本阶段开发、交付或完成的前置条件。云端使用版本化合成样本和独立数值参考，实际引擎运行按可用条件单独记录。

当前整体目标保持进行中。暂不开发新的隔离适配器，保留已有运行器和沙箱检查；兼容层与可信回归测试继续开发、执行。延期验收和未运行的 Google 对照分别如实记录，不能据此把 API 兼容目标标为受阻，也不能将未验证的运行平台标为已支持。

以固定版本官方 API 的全量签名为总跟踪清单，按真实项目依赖确定实施顺序。范围不止于简单 NDVI 示例或当前支持的常用算子。官方客户端负责 JavaScript 对象构造与序列化；本地后端逐步补齐实际算法。

## 当前基线

- 最新第三十八批新增 **20个有限归约入口（含2个已弃用别名）**：总体／样本方差、minMax、乘积、计数／频数表、逻辑／位归约及 repeat／forEach。完整回归 **3843 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS二十三项结果一致，两行分组CSV实际写出与结果读回通过。名称 **539／991（54.39%）** 仅为入口统计，不代表完整语义兼容。countEvery 保持零输入列，重复值频数表避免重复输出计费，1000行重复值通过原50000预算；1000个不同值的完整表格路径仍超限。依赖及运行环境未变，Google／真实数据／生产验收仍未完成。见 reports/gee-python-wave38.json。

- 第三十七批历史记录：新增 **28个有限计算入口**：DateRange9、属性统计14、组合归约4、集合flatten1，并扩展构造／map及List.reduce／reduceColumns。完整回归 **3722 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十四项结果一致，两行分组CSV通过合成dispatch／worker／实际写出与结果读回。名称 **519／991（52.37%）** 仅为入口统计，不代表完整语义兼容。1000行统计在原50000预算内通过；新增模块按描述／校验／计算／输出拆分，依赖及运行环境未变。未部署，Google／真实数据／生产验收仍未完成。见 reports/gee-python-wave37.json。

- 第三十六批历史记录：新增 **14个有限静态入口**：UTC日历4、Array选择3、内联表3、Number.expression1、String正则3，并扩展已有Dictionary.select/remove的RE2正则选择。完整回归 **3644 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十三项结果一致，两行CSV通过合成dispatch／worker／结果读回。名称 **491／991（49.55%）** 仅为入口统计，不代表完整语义兼容。固定RE2依赖的OSV／PyPI已知告警查询为0，原锁定包版本未变；50000工作预算保持。未启动或部署业务服务，Google／真实数据／生产验收仍未完成。见 reports/gee-python-wave36.json。

- 第三十五批历史记录：新增 **61个有限静态入口**：Number类型转换24、Array类型转换26、特殊函数8、容器筛选3，包含25个单列别名。最终完整回归 **3409 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十一项输出一致，三行CSV通过合成dispatch／worker／结果读回集成。名称 **477／991（48.13%）** 仅为入口统计。原预算保持，未改依赖或重建JVM，未启动业务服务；没有新增栅格／浏览器／生产／Google验收。整数舍入推断、Int64精确域和正则等限制单列，整体目标仍进行中。见 reports/gee-python-wave35.json 及 docs/gee-python/list.md。

- 第三十四批历史记录：39个名称入口，含16个实际Image科学函数及23个静态结构／解析／别名入口。冻结便携3180 passed／10 skipped，七个可信原生组件、前端11／类型／临时构建通过；Python／JS十项输出一致。名称416／991（41.98%）仅为入口，含本批12个别名。有限网格常量按需逐景绑定，不同atan2来源在隐式重采样前拒绝；4000景普通map保留原预算。Float32及极点政策明确，未部署，无完整Spark／服务／浏览器／Google验收。见 reports/gee-python-wave34.json、docs/gee-python/pixel-math.md。整体目标保持进行。

- 第三十三批历史记录：5组并行批量实现98个有限静态入口，Number25／Array36／List18／Dictionary10／String9。冻结便携2989 passed／9 skipped（排除4项延期原生测试），Python／JS10项组合输出与独立预期、前端11／类型／构建通过。名称377／991（38.04%）仅入口，含官方单列别名；没有完整参数／上下文／Google兼容声明。保留旧预算、历史List比较和数据／运行环境；未部署。采用整族定向验证后集中回归／CI发布，纯静态改动不重建未改JVM。见 reports/gee-python-wave33.json、docs/gee-python/static-families.md。

- 第三十二批历史记录：实际Smile RF explain三字段及有界字典投影／JSON任务，真实JVM与独立三树Gini参考和物理JSON读回通过。冻结源码2788 passed／3 skipped（排除4项延期原生测试），六组件与前端11／类型／构建通过；另有2项静态控制流精确图测试。普通大列表／表格的7项扫描回归已根因修复，原预算和样本保留。入口279／991（28.15%）仅名称；原50探针45编译不代表任意项目迁移率。模型解释仍有参数、资源和原始OOB政策边界，无Google对照或完整Spark／服务／浏览器／部署验收。见 reports/gee-python-wave32.json、docs/gee-python/rf-explanation.md。

- 第三十一批历史记录：RF分类后filter／无排序limit／randomColumn→验证矩阵／getInfo／CSV，保留不可变分类规格和顺序列谱系；取样与分类后操作合计16步、表50000与RF150000分别计费。64项弱身份校验缓存预充开销、突变拒绝、淘汰全量校验。冻结源码2690 passed／3 skipped（另排除4项延期原生测试），六个可信组件和前端11／类型／构建通过；显式排除类别字段的真实JVM模型产生32→16→16→8行与[[3,0],[0,5]]合成计数，实际JSON／CSV读回通过。入口278／991（28.05%）仍只表示名称。未部署，无完整Spark／服务／浏览器／Google对照；完整API和生产目标保持进行中。见 reports/gee-python-wave31.json、docs/gee-python/classified-tables.md。

- 第三十批历史记录：MD／RF的inputProperties省略或null时只读取实际声明band_order，显式列表优先，保留完整字段顺序；新增内联集合级Element元数据及行操作传递。扫描／复制分开预充，get返回独立嵌套值，保留50000预算。冻结源码2640 passed／3 skipped（另排除4项延期原生测试），六个可信JVM／栅格组件及前端11／类型／构建通过；从官方客户端省略参数编译出的规格实际进入32行取样／16＋16划分／Smile训练与预测。入口仍278／991（28.05%），本批扩展已有方法参数，不扩大完整兼容率。未部署，无完整Spark／服务／浏览器／Google验收；sampleRegions v1默认字段、动态取样元数据修改、邻域、其他模式及完整API仍待做。见 reports/gee-python-wave30.json、docs/gee-python/training-schema.md。

- 第二十九批历史记录：有限randomColumn、采样列谱系、新增／覆盖字段的CSV与getInfo、RF训练／预测／验证指标组合；修复真实Image.sample元数据拒绝和可信直接样本表回归。schema缓存只复用不可变身份并预付新副本开销，保留50000编译预算。冻结源码2600 passed／3 skipped（另排除4项延期原生测试），六个可信JVM／栅格组件及前端11／类型／构建通过。实际32行样本按本地随机值划分16／16并进入真实Smile模型，验证／训练矩阵频数通过；无完整Spark／服务／浏览器／部署／Google对照。入口278／991（28.05%）仅为名字；邻域、自动schema、其他分类模式和完整API目标仍进行中。见 reports/gee-python-wave29.json 与 docs/gee-python/random-split.md。

- 第二十八批历史记录：新增实际 Image.sample：有限 footprint／ROI、factor 或近似 numPixels、固定本地 seed、dropNulls、中心几何与 band_order 元数据，继续复用采样表筛选／训练／RF验证／getInfo／CSV 路由。原 sampleRegions v1 保留，v2 经同一公开进程进入独立原生 SPI；缺失瓦片可保留空值，所有源键／形状／重复／解码和输出预算仍验证。冻结源码完整回归2493 passed／3 skipped（另排除4项延期原生测试），前端11／类型检查／构建通过；五个可信独立 JVM／栅格组件通过，取样有独立网格／随机参考。入口277／991（27.95%）仅表示名称，不是完整参数／数值兼容率。未部署，无完整Spark／服务／浏览器／Google对照；邻域、随机列、自动schema及完整API仍待实现。见 reports/gee-python-wave28.json、docs/gee-python/image-sampling.md。

- 第二十七批历史记录：接通真实 RF 的 FeatureCollection.classify、训练重代入矩阵与独立表 errorMatrix 的七种访问器，以及受原有任务权限／物理文件边界保护的 JSON getInfo／CSV 导出。根作用域仅缓存不可变取样／训练 IR；相同训练与预测表复用固定 sampler，mapped 环境不缓存。空表保留空行，显式顺序空矩阵为零，未定义指标失败。完整便携回归2413 passed／3 skipped（另排除4项延期原生测试），前端11／类型检查／构建通过；实际可信 JVM 验证 Float64 要素预测、32行重代入频数、空查询与7非法查询，并继续通过四个栅格组件。入口仍为276／991（27.85%），本批扩展已有方法语义；未部署，无完整Spark／浏览器／Google同数据验收。随机列、其他模式／分类器、动态指标通用算术、分类后筛选、模型保存及完整API兼容仍待做。见 reports/gee-python-wave27.json 与 docs/gee-python/rf-validation.md。

- 官方客户端版本和提交见 `vendor/earthengine-js/upstream-lock.json`。
- 官方 Python 客户端已按同一提交固定，见 `vendor/earthengine-python/upstream-lock.json`；Python 和 JS 共享本地 EE 编译器及算法支持边界，Python/openEO `connection` 继续保留。
- 第二十六批历史实现有限真实 Smile1.5.3 RandomForest：六参数保留，内联表／采样表只在可信 JVM 训练，opaque 模型仅用于影像分类，保留来源／网格／掩膜／Float64；独立依赖锁和 SPI 构建，未部署到 .native。便携完整回归2293 passed／3 skipped（排除4项延期原生测试），前端11 passed／TypeScript与临时构建通过；新增3项 Python／JS 官方 SDK 图一致性，四个真实 tile 内核通过。RF1000行×8特征×100树规模组件与精度／种子／线程／非法输入控制单列报告；Unicode wire 名称按码点一致处理，最终原生定向复核另记。API入口276／991（27.85%）仅统计名字，不是完整兼容率。见 reports/gee-python-wave26.json、docs/gee-python/random-forest.md。RF表分类／explain／验证矩阵／随机列／其他模式／自动band_order及完整Spark／服务／浏览器／Google验收仍未完成。
- 前一批历史记录见 `docs/gee-compatibility.md`。第二十五批补齐有限 Image.remap、Filter.expression 和取样表 filter／无排序 limit，操作与训练共享预算，保留训练／目标来源及网格。示例 30 串联标签重映射、真实取样和筛选、训练与分类；便携 Python 2068 passed／3 skipped（另排除 4 项原生测试），前端 11 passed／构建通过，77 项 Python／JS SDK 图一致性，三个可信独立 JVM tile 内核通过。见 `reports/gee-python-wave25.json` 和取样语法文档。本批未部署，完整 Spark、隔离运行器／浏览器、真实数据和 Google 同数据验收未运行。当时随机森林未实现，依赖及算法路线单列 `docs/gee-python/random-forest-roadmap.md`；动态表的新列／排序／标量结果／验证矩阵、其余采样／分类器、完整球面／CRS／Float64 算法及高级时序仍有缺口。
- Python API 清单见 `reports/gee-python-api-inventory.json`，保留 991 项签名、2451 项参数及公开 Python 绑定。原有 50 项 Python 定向探针当前为 45 项编译通过、5 项明确拒绝；方法、参数和探针数量均不代表完整兼容率。已补有限表格回归、FeatureCollection、数值时间度量及 inner Join、Number.format、有界 String 和固定形状栅格数组，并串联合成表格预测、最近前后观测插值及像素投影；动态数组、通用设计矩阵的栅格回归、其他采样／分类算法仍有缺口，有限精度评估不能代替完整分类器实现。完整 Linux 运行按阶段调整延期。最新局部实现及限制持续写入 `docs/gee-python/list.md`。
- 复杂工作流来源和缺口见 `audit/gee-complex-compat-v1/findings.json`。
- 有效探针为 `audit/gee-complex-compat-v1/probe-run-v2/validation.json`：50 个表达式成功序列化，3 个阳性对照编译通过，43 个操作/语义探针被拒绝，4 个数据/波段探针被拒绝；另有 14 个规模编译检查、3 个原生 runner 检查。该定向抽查不是全 API 兼容率。
- 历史两波段均值模拟目录探针中，30 景生成 335 节点，50 景超过现有 500 节点限制；该计数属于优化前证据。长时序执行与吞吐仍需单独验证。

## 实施顺序

按用户2026-10-23要求，后续以算子族批量并行开发、统一集成为默认；每组做定向计算／参数验证，冻结整批后统一回归和发布。不得为了增加入口比例注册空实现，也不逐个小函数重复完整发布。

1. 建立全量签名与重载清单、公开项目样本、能力矩阵和可重复回归。分别记录支持、部分支持、未支持、语义差异及验证证据。
2. 优先修复 Python 实测失败：GeoJSON／投影解码、Filter.notNull、Dictionary 空 keys／缺键和 List.sequence 参数语义；再补 QA 位运算、真实整数类型转换、unmask 与掩膜/足迹、qualityMosaic、日期运算、逐景动态属性、常量栅格及投影网格。
3. 实现紧凑的精确观测加载和长时序归约，保留同日多景身份、排序、波段、掩膜与日期边界；保留资源预算及图校验。
4. 补集合 Join、时间匹配、矢量/批量区域统计、邻域与距离算子、插值和多输出归约。
5. 补数组、矩阵、回归、采样、分类训练/预测与精度评估；逐步支持谐波、HISTARFM、随机森林等完整工作流。
6. 支持 LandTrendr 等高级时序算法，并持续覆盖其他真实项目需要的算法；按算法性质实现并验证，不能以近似占位实现冒充兼容。
7. 补地图/图表与 GEE 应用交互、本地模块解析及迁移诊断。对外部用户模块采用显式导入、许可/版本固定和本地依赖解析。
8. 为新增数据集建立独立适配和版本化合成验证，包括 Landsat、气象、DEM、QA/云概率及用户矢量；本机真实数据验收延期，新增 STAC 数据不自动获得 EE 别名。

本阶段交付可以在现有便携环境重复计算和审查的合成工作流，持续回归已有功能。完整运行器部署与真实数据全流程另期验收。具体实现前读取对应模块和直接调用方，保持模块化边界。

## 完成判据

- 每个声明支持的方法和重载均具备正向、参数/类型错误、缺测与边界验证；没有静默丢弃参数或替换算法。
- 分开记录 S：官方 SDK 序列化，C：本地编译，E：实际引擎运行，N：独立数值基准，G：可取得的 Google 同数据对照。没有 G 证据时明确说明。
- 科学验证对齐数据版本、缩放/偏移、单位、波段名称与顺序、网格/CRS、时间、NoData、掩膜和边界权重，给出误差与容差依据。
- 以版本化合成样本复现公开项目计算步骤，覆盖多景、跨年、Join、回归、分类和高级时序；原有地图/图表、任务、取消/恢复和导出合同保持回归。完整部署与本机真实数据全流程延期，不作为本阶段完成前置条件。
- 规模验证同时记录输入范围、景数、图规模、时间、峰值资源和失败边界；编译成功不能代替运行或性能验收。
- 全量清单中的剩余差异明确可查；阶段通过不能用于宣称全面兼容。只有约定范围均已完成且剩余差异经过明确评审，才可关闭相应目标。

## 持续约束

- 继续保留 macOS 原生运行和 Seatbelt 沙箱；新的 Linux 执行／隔离适配及其验收延期，已有运行器继续拒绝无隔离回退。不重建旧虚拟机或容器；Windows 虚拟机不动。
- 用户脚本与计算保持文件、网络、凭据和资源隔离，分析默认禁止公网出站。不得为兼容性放宽隔离或自动外发数据。
- 保留科研数据、现有账号、结果、固定依赖和历史证据；不自动恢复用户已删除的旧数据库。
- Google 全球数据目录、私有 assets、Drive/Cloud Storage 等服务依赖单独说明，并提供明确的本地迁移路径；客户端兼容不代表拥有 Google 云端数据或专有服务。

## 目标的记录与关闭

本文件是当前可持久化、可审查的工程目标，后台任务状态以运行平台为准。后续提交持续更新兼容清单、实测结果和剩余缺口；目标在全部约定验收满足前保持进行中。
