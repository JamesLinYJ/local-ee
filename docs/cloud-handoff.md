# 云端开发交接

## 第三十一批最新起点

从最新main继续，不恢复历史handoff；本批基线3486478。已接通RF分类后的filter、无排序limit、randomColumn，再进入errorMatrix／getInfo／CSV；分类规格与后续列分开，取样前置和分类后合计16步／累计50000，RF150000继续独立并继承已有表工作。64项弱身份校验缓存只保存不可变谱系和计数，预充查找／记录／新列复制，不存样本、模型或tracer；突变拒绝，淘汰后全量校验。16步覆盖同列反复覆盖，未提高预算或缩小夹具。

冻结兼容源码完整回归2690 passed／3 skipped（另排除4项延期原生测试），六个可信JVM／栅格组件通过，前端11／类型／临时构建通过；之后仅补机器清单限制文案并通过5项清单检查。实际样本32行经显式reflectance输入的真实模型预测后，留出筛选16、加随机列16、限量8；独立ID／真实中心点几何／哈希／矩阵频数以及物理JSON／CSV写出读回通过。合成矩阵[[3,0],[0,5]]不是实际预测能力或Google对照。配对JAR／manifest与确定退出记录保存在新audit，旧wave29／30材料及完整Python目录共19项摘要保持不变。

本批发现并修正预充顺序、固定最大列数误计费、反复扫描产生的16步误拒绝、矩阵未继承表工作及新列复制计费；拆分时旧引用失败和一次全量旧断言失败证据保留。最终源复审无已确认剩余缺陷，只是源码审查，测试／组件证据分别记录。入口278／991（28.05%）不变，仅统计名称；50定向探针45编译／5拒绝。见docs/gee-python/classified-tables.md、examples/36_GEE_python_classified_tables.py、reports/gee-python-wave31.json。

未部署；没有完整Spark／RDD／批任务／HTTP／浏览器／沙箱或Google同数据验收。下一步继续其他模式、动态取样变换、邻域和高级时序等完整API缺口。账号、科研数据、.native和固定依赖保留，不启动VM、容器或服务。


## 第三十批历史起点

从远端最新main继续；本批基线 `32799e8e4e7d95ad5d86e500fe60a2b53b80facc`。省略／null的训练字段只取内联集合或已验证Image.sample v2元数据band_order；显式非null列表优先，空列表拒绝。保留完整声明顺序，不猜首行字段或删除类别。引擎继续使用已确定schema的原规格，未新增Java算法／依赖。内联集合的Element元数据与筛选／limit／randomColumn／map到Feature独立复制；扫描前预付预算、get嵌套返回不别名，v1和动态取样修改限制明确。

冻结源码完整回归 **2640 passed／3 skipped**（另排除4项延期原生测试），六个可信JVM／栅格组件通过，前端11／类型／临时构建通过。自动RF规格先与显式完整band_order比较，再实际进入32行样本→16／16划分→Smile训练／预测／矩阵；仅组件证明，无SparkContext／RDD／批任务／沙箱／HTTP／浏览器／部署／Google对照。旧wave29配对产物摘要已在本轮前后核对不变，当前匹配JAR／manifest和网关退出证据在新audit。独立源码复审发现的扫描预充／get别名已修复；一次全量旧断言失败记录保留，更新为正向schema和opaque模型拒绝后重跑通过。

入口278／991（28.05%）仅为名称，本批未新增入口；完整Python目录字节不变，50探针45编译／5拒绝。语法／示例／报告为 `docs/gee-python/training-schema.md`、`examples/35_GEE_python_training_schema.py`、`reports/gee-python-wave30.json`。下一步继续v1集合元数据、动态变换、邻域／其他分类模式及高级时序，不以已过组件缩减完整API目标。保留账号、数据、.native和锁定依赖；不启动VM、容器或服务，不恢复历史handoff分支。

## 第二十九批历史起点

从远端最新main续作，不恢复历史handoff。此批基线 `f7414cfa0a91bc5e3e68df5c95d714f3bce3abf7`；有限randomColumn支持静态／采样表、typed行键、uniform／normal与新增／覆盖列。schema按完整操作链推导，训练／预测／矩阵与getInfo／CSV保留真实字段。Image.sample的根band_order严格按来源验证；无来源可信v1表保留原有合同，不能授权未追踪的变换或任意根元数据。

冻结源码完整回归 **2600 passed／3 skipped**（另排除4项延期原生测试），六个可信独立JVM／栅格组件通过；新增实际authenticated-loopback Py4J链路为32行取样→16／16随机划分→真实Smile训练／预测／矩阵。仅组件证明，无SparkContext／RDD适配／完整批任务／浏览器／部署／Google同数据验收。原50探针45编译／5拒绝，Python完整目录字节不变；入口278／991（28.05%）只统计名称。

本地SHA256随机序列不是Google RNG oracle。有限schema缓存以强引用的不可变身份匹配、冻结内容、返回新副本并预充既有50000预算；不缓存像素、随机值或模型。完整回归曾暴露可信直接表回归及Py4J preexec线程fork崩溃，修复后重跑，原失败证据仍保留。可信测试启动使用带认证的回环、无Python preexec回调的独立session、超时与确定回收；应用隔离未改变。

前端11／类型检查／临时构建通过，未部署；语法、示例和报告见 `docs/gee-python/random-split.md`、`examples/34_GEE_python_random_split.py`、`reports/gee-python-wave29.json`。邻域／focal、自动训练schema、其他模式／分类器、通用动态指标、分类后变换、高级时序及完整API仍待做。账号、数据、现有.native、锁定依赖保留；不启动VM、容器或服务。

## 第二十八批历史起点

从最新 main 续作；本批基线 `b2b16450fc2b16a29ace791bf1458bf4ca5e47e7`，新增有限实际 Image.sample 取样，经同一公开进程的严格 v2 字符串规格进入内部 SPI。有限网格左连接实际瓦片，保留缺测可选 null、全局稳定抽样和结果顺序，维持独立固定来源／网格、所有解码及输出预算；band_order 为规格元数据，训练仍需显式 inputProperties。

冻结源码完整便携回归 **2493 passed／3 skipped**（另排除4项延期原生测试），五个可信独立 JVM／栅格组件与前端11／类型检查／临时构建通过。原50探针45编译／5拒绝，完整Python目录字节保持；入口277／991（27.95%）只统计名字。没有完整Spark、服务／浏览器、部署或Google对照；本地固定哈希不保证Google抽中行相同。见 `docs/gee-python/image-sampling.md`、`reports/gee-python-wave28.json`。邻域需要跨瓦片 halo，未实现；随机列、自动训练schema、其他分类模式及完整API目标仍进行中。保留账号、数据、.native与固定依赖，不启动VM／容器／服务。

## 第二十七批历史起点

从远端最新 main 继续，不恢复旧 handoff 分支。此批基线为 `05718cff1d4603ac1a9933b76298012059ef9ef6`，实现真实 RF 要素分类、训练重代入与验证矩阵访问器、受控 JSON getInfo 与原有 CSV 导出。既有静态混淆矩阵／指标内核继续复用；分类器只在可信 JVM 训练与预测。相同根取样 IR 可复用训练分支，mapped 环境不缓存，训练网格独立。空表不造数据，未定义指标失败；规范字符串中的节点样式属性仍为数据。

最终便携 Python **2413 passed／3 skipped**，另排除4项延期原生测试。前端11／类型检查／临时构建通过；四个明确 opt-in 的实际栅格组件与新增实际 Float64 要素预测、32行重代入频数、空查询及7非法查询通过。无 SparkContext、完整沙箱／HTTP／浏览器、部署或 Google 同数据验收。Python／JS 新图比较按嵌入 JSON 的数值语义对齐，整数浮点拼写不保证字节一致。完整 Python 目录字节保持；入口276／991不变，本批扩展已有名字的实际语义。

规范见 `docs/gee-python/rf-validation.md` 和 `reports/gee-python-wave27.json`。新的 JSON sink 只接受直接受审查分类表／指标生产者；worker 仅发布可信 EE 任务的命名 JSON，所有读写沿用物理任务目录、权限及 no-follow 边界。JSON 分类表仍受 CSV／表／公开值／对象与 wire 复合限制。随机列、其他模式／算法、动态标量一般算术、分类后过滤及完整运行验收仍有缺口，目标保持 active。保留账号、数据、现有 .native 和四个固定 Smile 依赖；不启动服务、VM 或容器。

2026-10-21。用户明确要求由云端 Codex 继续开发与兼容性测试，当前优先 GEE Python：先探测、整理 `docs/gee-python/list.md`，再持续补齐兼容。完整平台目标仍见 `GOAL.md`、`AGENTS.md` 和 `docs/architecture.md`，不能把本轮客户端接入当成整个目标完成。

## 2026-10-22 云端续作

阶段范围已按用户最新要求调整：先完成 Python API／参数／计算语义兼容，再推进 JS；Linux 隔离执行、macOS／ARM64 及本机真实数据验收延期，不作为当前阶段前置条件。暂不开发新隔离适配器，继续运行便携兼容层与可信合成数值测试，保留现有运行器及沙箱检查。下文历史未运行记录继续保留，不代表当前目标受阻。

已从 `handoff/gee-python-cloud-20261021` 的 `71810c3448241051696545d0810f5348f1875290` 核对并继续。Linux 使用 Python 3.11、Node 24、uv 0.12.12；锁定依赖和便携测试环境已经实际验证，完整原生服务仍未在 Linux 适配。

本轮补齐公开 Python API／参数／绑定清单，修复命名 GeoJSON CRS、notNull、Dictionary／List.sequence，增加有界 ImageCollection 元数据 Join 和静态 Array／矩阵求值；独立数值参考只覆盖明确的静态算法／合成图。探针保持原有 50 个表达式，当前 44 项编译通过、6 项明确拒绝，不能据此推算完整 API 兼容率。完整清单和剩余限制见 `docs/gee-python/list.md`。

验证汇总见 `reports/gee-python-wave1.json`：Python 597 passed／7 skipped，前端 11 passed、TypeScript／构建通过；包含 8 项固定 Python／JS SDK 的共享编译结果回归。没有运行完整 Linux 后端、macOS 内核沙箱、ARM64 JNI 或私有影像验收。

探针守卫发现原 SDK 的可选弃用资产初始化会通过 urllib 请求 Google STAC；本地初始化现已跳过这项云目录操作，生产路径初始化／重置有网络入口拒绝回归。计数覆盖 Python transport／socket／DNS，并非内核抓包或用户程序隔离。

`GOAL.md` 已按用户要求持久化“Python 完整优先，随后 JS”的持续目标；文件本身记录目标与验收条件，后台任务状态以运行平台为准。

## 第二批 Python 兼容实现

第一批已验证提交 `6cd97801e5685dfb4c9e365f1328d321c369d0a8` 已在临时验证分支取得精确提交的 `python`／`frontend` 成功后，快进发布到 main。交接分支名保留为开发分支，不能据其远端位置判断 main 的最新状态。

第二批增加有界内联 FeatureCollection 操作、无权表格 linearFit／linearRegression、maxDifference 数值度量和 saveBest、Number.format 十进制子集及 String 构造／拼接预算。版本化合成表格示例串联筛选、OLS、矩阵预测和格式化，使用手算系数与 RMS 验证。详见 `reports/gee-python-wave2.json` 和 `docs/gee-python/list.md`，表格静态求值不构成栅格引擎验收。

本批 Linux Python **709 passed／7 skipped**；前端 **11 passed**，TypeScript／生产构建通过。7 项跳过仍为 3 项 opt-in JVM/Spark 和 4 项 macOS Seatbelt 检查。`uv sync --frozen --python 3.11`、`npm ci`、探针漂移检查和 Python API 清单字节重现均通过。

原有 50 项表达式保持不变，当前 45 项编译通过、5 项拒绝；其中影像集合回归仍明确拒绝，新增表格回归不能替代它。Python／JS 官方 SDK 共享回归增至 13 项，完整 JS 目标仍排在 Python 之后。后续委派子 agent 按用户要求固定使用 Luna、max 推理，文件所有权不得重叠。

Linux 用户／挂载／PID namespace 的临时能力探测在执行沙箱外成功；普通执行沙箱内的 `/proc/self/uid_map` 写限制不能推断为内核不支持。尚无验收通过的 Linux 执行适配器，因此生产用户代码继续拒绝在无对应原生隔离的平台执行。

## 第三批时间匹配工作流

第二批提交 `76fe99a271731e2e8e319195191fec5187ba9ea0` 已通过精确提交的 GitHub `python`／`frontend` 检查并快进发布到 main。第三批在此基础上将 Join 条件验证／求值拆到 `join_conditions.py`，增加唯一 maxDifference 与标量条件的 And 组合，以及有限 ImageCollection 的 `Join.inner`。不请求度量时保留 Or／Not 布尔筛选；请求度量时拒绝多重或歧义结构。

inner 输出匹配对 Feature，内部保留真实 Image；Feature 属性和同类 Image 映射结果可继续进入选波段、addBands、ImageCollection 计算。版本化 `ee-temporal-interpolation-v1.json` 串联最近前后观测、毫秒权重和像素插值，独立参考同时覆盖来源、掩膜和目标时间。详见 `reports/gee-python-wave3.json`；这些合成图数值测试不是原生栅格引擎执行。

本批 Linux Python **745 passed／7 skipped**，前端 **11 passed**、TypeScript 和构建通过；比第二批增加 36 项通过回归，跳过项目及原生平台限制不变。原大输出预算用例采用数值匹配键以单独命中物化／1 MB 上限；字符串扫描预算另有明确负控，没有放宽失败断言来隐藏回归。

原有 50 项表达式及 45 编译通过／5 拒绝不变，Python／JS 官方 SDK 共享编译回归增至 15 项。后续继续优先 Image.array*、逐像元回归、采样／分类训练预测与真实项目，Python 完整目标仍未完成。

## 第四批静态数组与 PCA

第三批提交 `ca9fdc9a9e0215e5ef98befd93a58e9f0f82d6b9` 已通过精确提交的 GitHub `python`／`frontend` 检查并快进 main。第四批在此基础上将 Array 类型／资源校验、布局、算术、归约及矩阵分解拆为独立模块，保留原导出与已有矩阵调用。

增加 19 项有限静态 Array 方法：同形算术、slice／project／repeat／cat、单输出 reduce／accum、实对称 eigen、Cholesky、行列式／迹／对角线／Frobenius 范数。版本化静态 PCA 串联中心化、样本协方差、投影、重建，并以独立闭式结果验证。审查发现的极值求和／均值抵消、中位数和矩阵迹中间溢出已修复，有限结果与真实溢出均有回归。方法存在、矩阵内核和静态 N 均不能代替 Image.array* 或栅格引擎验收。

本批 `uv sync --frozen`、全套 Python **830 passed／7 skipped**、`npm ci`、前端 **11 passed**、TypeScript／构建均通过。固定 Python 清单独立进程字节重现通过；原 50 探针仍为 50 S／45 C／5 拒绝，Python／JS 共享编译回归增至 19 项。新增参数限制、浮点／特征向量呈现政策和未运行项目见 `reports/gee-python-wave4.json` 与 `docs/gee-python/list.md`。

整体目标保持进行中。当前限制针对 Linux 隔离和原生平台／真实数据／Google 对照验收，离线兼容开发可以继续；仍需推进栅格数组、逐像元回归、分类及真实遥感全流程。

## 第五批固定形状栅格数组

阶段调整提交 `0e5964dc83640529d40a3a689169ae15bcf30e01` 为本批基线。Linux 隔离适配、macOS／ARM64 和本机真实数据验收继续延期；第五批直接推进 Python API 与合成数值验证。

新增独立的固定形状单数组波段 IR，支持 Image.toArray、arrayFlatten／Project／Transpose／Slice／Get／Length(s)／Reduce 和 matrixMultiply，并扩展同形数组 Image 算术与数组常量。算子降为既有标量像素图，不新增伪计算 handler 或公网回退。单数组波段、最多 8 轴／每轴 64／总 64 单元、非空轴，仍共享 50000 工作步和 500 图节点上限；不支持的动态形状、广播、掩膜坐标、数组直接导出和 Float64 callback 算术明确拒绝。

版本化 `ee-raster-projection-v1.json` 和示例 11 从静态合成训练表求 PCA 基，应用到本地 red／nir 像素，独立核对正交投影、重建、来源与整体掩膜。任一输入波段无效则所有输出分量均无效。rank0 arrayGet、静态 If／Dictionary 默认值类型保留、逻辑波段元数据和未知参数拒绝亦有回归；坐标解析另拆为模块。既有数组再次 toArray 的保留名称规则尚无 Google 对照。

本批锁定依赖、全套 Python **894 passed／7 skipped**、前端 **11 passed**、TypeScript／构建均通过；比第四批增加 64 项通过，Python／JS 官方 SDK 实际编译对照增至 21 项。固定全量 Python 清单独立进程字节重现通过；原 50 探针仍为 50 S／45 C／5 拒绝。数值证据使用独立测试图求值器，不标为实际栅格 E 或 Google G。详见 `reports/gee-python-wave5.json` 与 `docs/gee-python/list.md`。

## 第六批逐像元 linearFit

以第五批提交 `9b5ab413c070635f93ef8a9030e4d893b4095043` 为基线，将 linearFit 从内联表格扩展到有限 ImageCollection。规范模块 `raster_linear_fit.py` 用既有 Pixel IR 实现 x/y 完整行删除和两遍中心化 OLS，输出 scale／offset；n<2 或 x 方差为零时两者均掩膜。Collection 与显式 ImageSequence 支持 1..8 帧，保留同日和重复观测的身份／权重，输出 footprint 为各景并集，系数不继承某景日期。

仅接受两个同名同序标量波段、binary NoData 和 parallelScale=1；不忽略内存提示，非默认值明确拒绝。共享工作／500 节点和既有 Float32 callback 约束保留，显式不支持的 Float64 组合拒绝。通用多变量／多响应 linearRegression 仍未实现，原 50 探针仍为 50 S／45 C／5 拒绝。

示例 12 与版本化 `ee-raster-linear-trend-v1.json` 从每景真实时间生成相对 day，绑定本地网格、显式 toFloat，拟合并预测目标日期。闭式分数再经独立 numpy.linalg.lstsq 复核，涵盖同日两景、缺测、常数信号、低样本及范围外采样点。审查指出参考器曾未应用逐景空间范围：测试数据已改为一致的重叠覆盖，参考器在 grid 存在时施加查询 extent 与逐景多边形，另有点在 bbox 内但在三角景界外的控制；不能通过忽略几何来制造数值通过。

第六批锁定依赖、全套 Python **907 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，较上一批增加 13 项通过；Python／JS SDK 实际编译一致性增至 22 项。完整 Python API 清单独立进程字节重现通过。证据见 `reports/gee-python-wave6.json`；N 是独立采样点求值，不标为实际栅格 E、分数边界权重或 Google G。隔离／原生平台／私有数据验收继续按用户要求延期。

## 第七批误差矩阵与分类评估

以第六批提交 `66516d64ad0f143cdf0498c35fdf86b7061fcdcb` 为基线，新增有界静态 ConfusionMatrix 构造、array／order／accuracy／kappa 和内联 FeatureCollection.errorMatrix。typed integer Array 的计数非负，总和不超过 2^53；最多 64 类／4096 单元，共享工作预算。总体指标使用精确整数中间量；零分母明确拒绝。直接服务器对象 JSON、逐类指标和 Feature 属性中的矩阵对象仍拒绝，不能宣称完整 ConfusionMatrix 类兼容。

errorMatrix 限 1000 条完整整数标签记录；默认类别顺序含 0..max 的空档，显式顺序只计入两列都在类别表中的行，可用稀疏／负标签；显式 [] 是 0×0，空集合须给顺序。缺失／null 不静默跳过，示例 13 先调用 notNull，分别报告完整行数和实际计入行数。版本化样本有 18 完整行、17 计入行，按 [30,10,20] 输出不对称矩阵，总体准确率 12/17、Kappa 107/192；独立标签频数与机会一致概率复核数值。

第七批锁定依赖、Linux Python **955 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，比上一批增加 48 项通过回归；Python／JS SDK 实际编译一致性增至 24 项。原 50 探针仍为 50 S／45 C／5 拒绝，完整 Python API 清单独立进程字节重现通过。Luna max 独立复审未发现声明子集内可复现缺陷。详见 `reports/gee-python-wave7.json`；证据为 S/C/静态 N，无实际栅格 E/G。采样、分类器训练／预测及其遥感流程仍待实现；阶段延期项目不阻断继续开发。

## 第八批列表设计矩阵与回归

以第七批提交 `20d631c5614ba15e47d8aecaea21d6eac4f67689` 为基线，增加有界 List.zip／unzip／flatten／repeat／reverse／set／swap 和 List.reduce。布局保持类型化 Array 等原子值；zip/unzip 按官方描述取最短，科学示例另显式检查输入列长度，避免配错观测。布局最多 10000 个顶层值、flatten 深度 96，并受共享扫描／分配预算约束；负下标按末尾计数，越界不截断。

List.reduce 支持现有单输出归约及无权 linearFit／linearRegression，单值归约直接返回值、多输出返回具名字典；回归系数／RMS 保持 typed Array，复用内联表格的真实最小二乘内核。最多 1000 行／32 输入列，不完整行剔除，但同一行其他非空非法字段仍拒绝。示例 14 和 `ee-list-regression-v1.json` 用 1/x/x² 的列列表拟合两个响应，闭式系数为 `[[1,-2],[2,0.25],[-0.5,1.5]]`，第 4 时点预测 `[1,23]`；残差与设计列正交，RMS 分别为 sqrt(10/3)／sqrt(40/3)。无栅格 E 或 Google G。

空／全 null 的 sum/count=0、其他空归约与不足两个值的 sampleStdDev=null，first/last 跳过 null，均作为尚无 G 对照的本地边界政策记录。SDK 对 repeat(None,0/1) 省略必需 value；S 可序列化、C 缺参拒绝的证据保留，不猜测服务端补值。逐类准确率和 fscore 仍待可信 shape／零分母合同，不新增猜测实现。

本批锁定依赖、Linux Python **1036 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，较上一批增加 81 项通过；Python／JS SDK 实际编译一致性增至 27 项。首次全量运行发现历史测试仍断言回归仅有 reduceColumns，已按新范围更新断言并保留原失败记录；不回退真实能力来迁就旧文案。原 50 探针仍为 50 S／45 C／5 拒绝，固定 Python API 清单字节重现通过。详见 `reports/gee-python-wave8.json`，整体目标保持进行中。

## 第九批最小距离训练与独立验证

以第八批提交 `3fdaf8d2f0e11dd05335ed2b69204f10ba398782` 为基线，增加 Classifier.minimumDistance／train／schema／setOutputMode、FeatureCollection.classify 和 Classifier.confusionMatrix 的有限真实计算。仅 Euclidean、kNearest=1、CLASSIFICATION，显式 1..8 个唯一平面输入属性，训练 1..1000 完整数值要素、整数类别 0..63，subsampling=1／seed=0；受共享工作预算限制，大小上限的组合不保证可全部执行。

模型以不可变 Fraction 保存 binary64 输入的精确均值，用距离平方验证唯一最近类；等距拒绝，不猜 tie。这是本地数值政策，尚无 Google／Smile 逐步浮点对照。要素分类保留原属性／几何／ID，输出属性碰撞拒绝；重代入混淆矩阵真实重预测训练行，轴从 0 到最大类别并含空档。直接／嵌套模型 JSON、图像分类、其他模式／距离／k 和随机子采样仍拒绝。

示例 15 与 `ee-minimum-distance-v1.json` 的两类均值为 `(2,2/3)`、`(7,2/3)`，训练离群点实际分错，准确率 5/6；独立验证预测 `[1,3,3,1,3]`，顺序 [3,1] 的矩阵为 `[[2,1],[1,1]]`，准确率 3/5、Kappa 1/6。NumPy 独立均值／距离与手算矩阵验证了真实训练和验证分离，不以最近训练点冒充最近类均值。

第九批锁定依赖、Linux Python **1091 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，增加 55 项通过；Python／JS 实际 SDK 一致性增至 30 项。父审查发现并修复 falsey 参数被默认值吞掉和带点属性名验证不一致；回归保留明确拒绝。Luna max 复审未发现声明范围内剩余缺陷。原 50 探针仍 50 S／45 C／5 拒绝，完整清单字节重现通过；证据为 S/C/静态 N，无栅格 E/G，详见 `reports/gee-python-wave9.json`。

## 第十批栅格 linearRegression 与多响应

以第九批提交 `dd255b08d97ed799672b975fba92e1a9c7051a3b` 为基线，补 ImageCollection.reduce(linearRegression) 的有限实际计算：numX=1 过原点，或 numX=2 且首列为可证明的字面量单位截距；numY=1..4、1..8 同名同序标量帧、parallelScale=1。所有预测变量／响应共用完整行删除，n<=numX 或退化时系数与 RMS 全掩膜；RMS 分母为 n，系数保持 (numX,numY) 行主序，残差为 (numY,)。现有 linearFit 共用帧校验，数值方法不变。

新增真实多数组波段容器保存 coefficients／residuals，逻辑名／掩膜／来源独立于标量存储。选择单数组后继续 flatten／get；bundle 仅精确选择／rename／元数据和 typed Image 包装，真正 cast、通用数组组合和直接导出拒绝。总 array cells<=64，50000 工作与 500 图节点上限保留。

示例 16 使用四景双响应，在同一联合完整行模型下分别物化六个响应输出。完整系数／RMS／预测组合确实超过 500 节点；单响应系数各 418、RMS 各 497、预测各 424 节点，不提高上限或丢弃另一响应掩膜。版本化样本 pixel0 的 offset/scale 为 `(0.7,2.2)` 与 `(5,2)`；pixel1 因第二响应缺测，两个响应都删除一行，第一响应变为 `(17/14,29/14)`、RMS sqrt(3/14)、x=2 预测 75/14。另三个位置因秩不足／低样本掩膜，包括在所有 bbox 内但不被两景梯形覆盖的点。独立 SVD 与样点图求值验证，非 E/G。

第十批锁定依赖、Linux Python **1120 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，增加 29 项通过；Python／JS SDK 一致性 33 项，Luna max 复审通过。原 50 表达式仍 50 S／45 C／5 拒绝，但原回归探针使用 5 bands 与 3 inputs 不匹配，现改为准确的数量错误；这项拒绝不再表示全体栅格回归未实现。原探针源码／参数／序列化均保持不变，完整 Python 清单字节重现通过。详见 `reports/gee-python-wave10.json`；通用多变量系统、动态数组、权重、紧凑图与实际 E/G 仍待完成。

## 第十一批紧凑单波段元数据

以第十批提交 `b3ed6d2148c8472b4941e788664a8703b577061e` 为基线，新增独立 `band_labels.py`：延迟 singleton bands 维度及改名，相邻待生成改名直接保存最终标签，下一真实进程使用时按原规则物化。Graph.node 仍返回普通引用，image／finish 在输出前物化；数值 callback、Float32 转换、mask／unmask／clip、常量和时间归约边界不变，不放宽 500 节点或共享工作预算。

示例 16 原六条图从系数 418、RMS 497、预测 424（各两条）降至 333／394／337；同一版本化输入的数值／NoData 样点及 callback 多重集与优化前一致。完整四系数、双响应预测现在分别 405／413 节点，独立 SVD 数值通过；完整双 RMS 与八字段组合仍超过 500，测试要求明确拒绝。新增共享算术的不同标签／操作数位置、掩膜与非矩形景界、同日／重复观测及真实超限算术控制。

锁定依赖、Linux Python **1129 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，增加 9 项通过；Python／JS SDK 一致性仍 33 项。原 50 探针仍 50 S／45 C／5 拒绝，表达式和诊断均未改；完整 Python 清单字节重现通过。Luna max 复审未发现声明范围内缺陷。详见 `reports/gee-python-wave11.json`；证据为 S/C/独立样点 N，无实际 E/G。通用设计矩阵、动态数组和完整分类／采样继续开发，阶段延期不阻塞目标。

## 第十二批静态方阵分解与光谱混合

以第十一批提交 `c16a11c8a03e09d4c9d1be30fcc1d8dad69fd2aa` 为基线，在独立 `array_decompositions.py` 实现 Array.matrixQRDecomposition／matrixLUDecomposition／matrixSingularValueDecomposition，均仅接受必填 array 的非空静态方阵。返回 typed Array 字典，形状 n×n：QR 的 Q／R，LU 的 L／U／P 满足 P×A=L×U，SVD 的 U／S／V 满足 A=U×S×Vᵀ。输入不修改，输出只读；先检查合并输出 <=10000 cells 和共享 50000 步预算，再复制或分解。

QR／SVD 使用 NumPy/LAPACK，符号和重复值子空间基为已注明的本地政策，尚无 Google/EJML 对照。LU 手工实现首次最大值部分选主元，同步交换已有 L 列；计算零主元和非有限消元明确拒绝，没有添加近似秩容差。QR／SVD 可重建秩亏／零矩阵，矩形 full／thin 输出形状未确认而明确拒绝，不宣称栅格分解。

示例 17 与 `ee-matrix-unmixing-v1.json` 以三个正数、非正交的合成光谱端元和四组混合观测，分别走 QR、LU、SVD 因子字典 → Array.matrixSolve／Multiply，输出实际丰度和重建。独立 Fraction 验证 det=9/25、完整逆矩阵及最后样本噪声增量 `(7/360,-13/360,1/60)`，含噪解 `(151/360,131/360,13/60)`；三路误差均在 3e-13 内，网络尝试 0。属于静态矩阵工作流，不是 Image.unmix 或非负／和为一约束求解器。

锁定依赖、Linux Python **1174 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，增加 45 项通过；其中新分解测试 38、工作流 4、Python／JS SDK 一致性新增 3，总一致性 36。Luna max 独立复审与 42 项定向测试通过。原 50 探针仍 50 S／45 C／5 拒绝且字节不变，完整 Python 清单字节重现通过，见 `reports/gee-python-wave12.json`。本批没有新增 TypeScript 层；官方 JS 序列化仅作共享后端回归。无实际栅格 E／Google G，阶段延期不阻断后续 Python API 开发。

## 第十三批静态设计的栅格最小二乘

以第十二批提交 `a3c39da476df310efc02b4ffac97b76232bd5046` 为基线，在独立 `raster_matrix_solve.py` 实现有限 Image.matrixSolve，单数组波段 toFloat 也执行逐 cell 的真实转换。A 为静态字面量及保留量化顺序的 cast 链，B 为实际栅格数组，双方显式 Float32；A(m,n) 限 m<=8、n<=4、m>=n，B(m,k) 限 k<=4。预充预算后计算本地 NumPy 满列秩伪逆，降成既有像素乘加，整体掩膜、左属性和源回退保留；任一 RHS 缺测掩膜完整解，不做观测行删除。

父审查修复共享 cast 尾链重复求值，现按 Pixel 对象缓存每层量化；16777217 的 Float32 结果仍为 16777216。总输入 64 cells、常量 500 unique nodes、共享 50000 工作和 500 进程节点保持，最大形状的真实图仍可明确超限。动态设计、欠定／秩亏、非有限伪逆、数组 toDouble 与未知参数拒绝；NumPy 秩判定、有限源网格和 callback 舍入只声明本地政策，不宣称 Google/EJML 等价。

示例 18 与版本化 `ee-raster-least-squares-v1.json` 串联实际估计／重建／残差图，分别 70／97／116 节点。手推伪逆和 Fraction 独立校核含噪解 `(119/220,97/220)` 与残差 `(-1/44,-1/44,3/44)`，覆盖零值、负丰度、缺测与非矩形景界，容差 2e-6、网络尝试 0；不是 Image.unmix 或约束解混。

锁定依赖、Linux Python **1201 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，增加 27 项通过：矩阵数值／参数 22、工作流 3、Python／JS SDK 一致性新增 2（总 38）。Luna max 只读复审未发现声明范围内剩余缺陷。原 50 探针仍 50 S／45 C／5 拒绝且字节不变，完整 Python 清单字节重现通过，见 `reports/gee-python-wave13.json`。无实际栅格 E／Google G，不新增 TypeScript 层；生态核对另见 `docs/gee-python/ecosystem.md`，有限公开资料检索不构成“无人尝试”的结论。整体目标保持进行中。

## 第十四批定长时间数组与谐波拟合

以第十三批提交 `f779330169face0ef752846c954e552a95c96ce2` 为基线，独立模块实现 ImageCollection.toArrayPerBand 和 Image.arrayReshape。前者限 1..8 个同名同序标量帧、1..8 bands、axis=0、dropMasked=false 和总 64 cells；按集合顺序保留重复／同日观测，每个波段独立合并所有帧的有效掩膜。后者限单数组、有效常量 rank-1 lengths 和 1..8 维，允许一个 -1 推断，总 cells 不变，逐值／dtype／mask／name／source 不变。变长或动态／掩膜形状明确拒绝。

共享帧提取／schema helper 的小重构保留原回归行为和错误上下文。axis 使用既有 Integer 政策接收实际 SDK wire 0.0，拒绝 bool／非整数；dropMasked 仍须严格 bool false。静态 Number.sin／cos 使用有限弧度与 Float64 libm，整数限精确域 <=2^53，先计共享工作；独立有理数级数、象限、signed zero、缺参／非法数和预算负控共 33 项通过。libm 参数约减、同日稳定排序与有限源网格不是 Google 数值／投影等价声明。

示例 19 与版本化 `ee-harmonic-time-series-v1.json` 使用乱序的七景跨年合成时间序列，日期偏移 `[0,90,180,180,270,360,450]`，同日两景保留身份。SDK Date.difference → Number.sin／cos → 7×3 静态设计，再接逐波段时间数组、reshape、Float32 matrixSolve。精确 Fraction 校核含噪系数 `(407/1000,1/5,121/1000)`、正交残差和第 540 日预测 `207/1000`；独立 SVD 验证 Float32 输入、缺测、负值和 bbox 内非矩形景界外点，容差 2e-6。六个栅格输出图为 122／122／215／296／337／219 节点，另有三个静态元数据输出，网络尝试 0。

锁定依赖、Linux Python **1265 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，新增 64 项通过：集合／reshape 24、Number 33、工作流 3、SDK 一致性新增 4（总 42）。原 50 探针仍 50 S／45 C／5 拒绝且字节不变，991 项完整 Python 清单字节重现通过，见 `reports/gee-python-wave14.json`。S/C/静态及采样点 N 分别记录，无实际 E/G；动态数组、通用栅格设计、采样／分类和高级时序继续开发，整体目标保持进行中。

## 第十五批稳定范数与谐波振幅

以第十四批提交 `bcefdcee9ff2ca5f1a4a489797c40c6869e60ae1` 为基线，新增 `number_math.py` 统一有限静态 sin／cos／hypot／atan2 的严格参数、Float64 内核和工作预充。Array.hypot／atan2 使用同形 typed Array 和真实 NumPy 内核，结果有限只读，复制／内核前按 5×cells+1 计费。Number／Array.atan2 按 pinned SDK 文档采用 x=left、y=right；社区教程使用相反顺序，已在 `docs/gee-python/numerical-policies.md` 登记冲突和未做 Google 对照，不能把独立数学参考说成服务端轴顺序实测。

Image.hypot 用既有 Pixel 的 max/min／比例／平方根实际计算，保留广播／命名、左属性、来源和各波段掩膜，最后显式 Float32。3e30／4e30 与 3e-30／4e-30 避免直接平方问题；动态范数超 Float32 仍可能为 inf，已知常量溢出预检拒绝，回归覆盖两种路径。父审修复预检将另一非 bool 值截成 int 和 NoData int(None) 的问题。Float64 callback 拒绝、共享 50000 工作／500 图节点保持，没有新增数学进程白名单。

固定 GeoTrellis ScriptBuilder 源码的 arctan2 仍标 TODO，JAR 到 source commit 的构建映射未证明；Image.atan2 继续明确拒绝，这是一项 API 缺口，不把整个兼容目标标为受阻。示例 20 复用七景日期／集合数组／矩阵求解 builder，通过实际 Image.hypot 输出振幅；正负 `(3/10,2/5)` 均为 1/2，零向量为 0，含噪为 `sqrt(54641)/1000`。Fraction 正规方程／平方根参考、独立 Decimal 向量控制和缺测／非矩形景界验证通过，振幅／系数／截距／预测为 200／215／139／219 节点，网络尝试 0，不包含栅格相位。

锁定依赖、Linux Python **1303 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，新增 38 项通过：向量数值／参数 33、振幅工作流 2、SDK 一致性新增 3（总 45）。原 50 探针仍 50 S／45 C／5 拒绝且字节不变，全量 Python 清单字节重现通过，见 `reports/gee-python-wave15.json`。独立 Luna max 复审、S/C/静态及采样点 N 与未运行的 E/G 分开记录；其余数组、采样／分类及高级工作流继续推进。

## 第十六批轴布局与双响应数组求解

以第十五批提交 `b20edec331c1e61d493a80f8c8a8a8f901e5199f` 为基线，新增独立 `raster_array_concatenation.py`（142 行）实现 Image.arrayCat／arrayRepeat。cat 沿现有轴拼接真实行主序单元、合并整体掩膜并沿用左元数据／来源回退；repeat 按整轴块重复，copies 固定签名为 Image，本地要求单标量波段、有效纯常量正整数，实际执行每层类型转换。动态／掩膜／空间限定次数、零／负值、空轴、多数组波段及形状不匹配明确拒绝；这是本地子集政策，不声称 Google 也有相同限制。

输出构造前计费并保留 rank 8、每轴／总单元 64、共享 50000 工作步和 500 图节点预算。父审修复次数解码把预算异常归为数值错误的问题，并补次数证明阶段的预算耗尽回归。Float32 将 `2.0000000000000004` 转成 2 后实际重复两次，无转换则拒绝；64 单元成功和超限、真实大图拒绝、源／几何／NoData、不可变输入均有回归。早期测试的样点数／错误措辞预期已校正；初始 64 单元探针输出超过图预算，改用紧凑合法探针验证形状边界，未提高任何预算。

示例 21 与版本化合成双响应样本串联排序、arrayRepeat 截距列、两次 axis1 arrayCat、toArrayPerBand／reshape、显式 Float32 matrixSolve，以及系数／拟合／残差。两个非比例响应由 Fraction 闭式和独立 SVD 核对，含正／负／零、噪声、联合缺测及非矩形边界，图节点分别为 208／284／328，网络入口尝试 0。

锁定依赖、Linux Python **1338 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，新增 35 项：布局／参数 31、工作流 2、SDK 一致性新增 2（总 47）。原 50 探针仍 50 S／45 C／5 拒绝且字节不变，全量 Python 清单字节重现通过，见 `reports/gee-python-wave16.json`。Luna max 独立复审 53 项通过（在最终计数转换／参数补充前）；完整最终测试和父审单独登记。S/C/采样点 N 通过，栅格 E／Google G 未运行，整体目标保持进行中。

## 第十七批矩阵描述量与四景样本协方差

以第十六批提交 `466248d938a70035d3a63ebf6d365b5ebc2c24b7` 为基线，新增 `raster_matrix_properties.py`（138 行）。Image.matrixDiagonal 从固定 rank2 矩形提取真实对角列并保留原单元转换；matrixToDiag 将显式 Float32 单列 1..8 行变成实际零填充对角矩阵。matrixTrace 限方阵 1..8，matrixDeterminant 限方阵 1..4，输出标量 Image；完整数组掩膜、名称／属性／来源保留，非对角线 NoData 同样掩膜结果。签名均严格接受唯一必填 value，矩形 trace 等限制是本地子集政策，固定官方说明没有证明所有形状／精度／结果类型。

每次迹加法、行列式乘法及有符号累加都显式转 Float32，避免仅末尾转换造成常量和栅格中间精度不一致。正式回归 `[1e8,1,-1e8]` 在两条路径均得 0、精确值为 1；有限 Float32 输入 2e38 的迹／行列式可为正无穷，而同样字面矩阵在编译折叠时拒绝。该常量／动态错误差异和非稳定多项式算法已写 `docs/gee-python/numerical-policies.md`，不声称稳定 LU 或 Google 等价。输出构造前保守计费，4 阶行列式预充 464 步、8 行 ToDiag 216 步；64 单元、50000 工作步和 500 图节点保持。实际一般稠密 4×4 栅格行列式仍超图预算拒绝，合法小整数常量 4×4 有 Fraction 消元数值正控。

示例 22 与版本化样本从四景真实合成 red／nir 数值堆为 4×2，H 中心化后计算 XᵀX/3，再取对角、对角矩阵、迹及行列式，没有替换成预计算协方差或只注册 reducer。第一样点矩阵 `[[5/3,2/3],[2/3,4/3]]`、迹 3、行列式 16/9；负协方差／奇异及零方差、联合缺测与非矩形边界均有独立 Fraction 和 NumPy ddof=1 参考。图节点为中心化 266、协方差 370、迹 310、行列式 374、对角列 308、对角矩阵 313，网络尝试 0。

Linux Python **1372 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，新增 34 项：矩阵布局／参数 28、工作流 2、SDK 一致性新增 4（总 51）。Luna max 最终独立复审 30 项通过，另有 40 个只读政策样点和参数边界检查，不额外加入 pytest 数量。早期测试的掩膜索引／矩阵波段／目录名以及 toDouble 提前拒绝的预期错误均已修正，没有放宽生产类型检查。原 50 探针和全量 Python 目录字节不变；报告见 `reports/gee-python-wave17.json`。S/C/采样点 N 与未运行的栅格 E／Google G 分开登记，整体目标保持进行中。

## 第十八批前缀运算、稳定范数与单数组选择

以第十七批提交 `111d72bc14d91d50f85f35b578e9368547195f98` 为基线，新增 `raster_array_accumulation.py`（90 行），扩展 `raster_matrix_properties.py`（171 行）。Image.arrayAccum 严格接受 input／axis 和可选 reducer，省略／null 默认 sum，真实支持 sum／min／max 的包含当前位置前缀；固定 rank1..8、现有轴、显式 Float32，每次更新转换，保持完整数组掩膜／名称／Image。其他 reducer 和 unweighted 修饰符拒绝，不静默丢弃；50000 工作步、64 单元和 500 图节点保持，输出前收费。

Image.matrixFnorm 对 rank2 Float32 单数组实际计算最大绝对值缩放、比例平方和、开方及乘回 scale，各阶段 Float32，保留完整输入掩膜。零安全除法使全零结果为零；3e30／4e30 和 3e-30／4e-30 分别约为 5e30／5e-30，以 Decimal、rtol3e-6／atol0 检查，未用宽绝对误差掩盖小值错误。动态最终溢出和已知常量编译拒绝有正式回归，逐步累计的抵消／溢出也分别记录于数值政策。

真实示例触发单波段 `toArrayPerBand().select('ndvi')` 原有拒绝。保留合法调用，单数组与多数组复用 exact-name／index／newNames 选择规则，保留单元引用／mask／source／元数据；未通过删除 select 避开问题。空／正则／重复选择器及非法改名仍拒绝，新增 13 项选择重载回归。初始测试参考的 leading sample 轴、提前拒绝的 unweighted 错误信息，以及选择参数变异时的 SDK ValueRef／tuple scope 处理均已校正，没有放宽生产检查。

示例 23 与版本化合成 NDVI 样本保留 2024-01-01 至 2025-01-01 的实际 366 天间隔与 day180 同日双景，逐景基准为明确输入的 0.25。第一像元累计和为 `[-1/20,1/10,-1/4,-1/5]`，异常平方范数 3/20；第二平方范数 3/8，第三为零，缺测／多边形外全部无效。Fraction 前缀、Decimal 根值和独立 NumPy 参考通过，网络 0；异常 88 节点、四个累计路径各 110、范数 176。初始输出标签 day365 已改为实际 day366，日期数据没有被更改。

Linux Python **1428 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，新增 56 项：累计／范数数值及参数 36、单数组选择 13、工作流 2、SDK 一致性新增 5（总 56）。Luna max 独立复审 70 项通过，早于最后选择与范数边界补充，完整最终套件及父审单独登记。原 50 探针及完整 Python 目录字节不变；报告见 `reports/gee-python-wave18.json`。S/C/采样点 N 与未运行的栅格 E／Google G 分开登记，整体目标继续。

## 第十九批最大值坐标与光谱原型选择

以第十八批 `1352470cce5695fb64d0ff9693cb58436fe46671` 为基线，新增 `array_argmax.py`（131 行），静态／栅格路由分别接入 Array.argmax(array) 和 Image.arrayArgmax(image)，严格拒绝未知／缺失参数。静态保留 dtype，按行主序严格大于更新，typed 空切片为 null、rank0 为 []，已有有限值／整数 ±2^53／10000 单元／rank8 限制保持。

栅格要求单个固定 rank1..8 数组，每个单元显式顶层 toFloat，通过真实 gt／if 构造首个最大值的每轴坐标，返回 shape(rank,)；完整输入掩膜、名称／Image 元数据／来源保持，非赢家单元缺测也使全部坐标无效。坐标暂以整数值 Float32 表示，没有证明 Google Integer dtype 等价；Double 输入需要用户显式量化，`[16777216,16777217]` 量化后并列选 0 有正式回归。rank0 空向量、标量／多数组波段明确拒绝。

静态扫描前计费 `2*cells+rank+1`，栅格扫描／构造前计费 `cells*(2*rank+4)+rank²+2*rank+metadata_work`。50000 工作、64 栅格单元和 500 图节点保持；63 个常量加一个真实栅格单元的 64 单元正控实际得到位置 63，而独立 64 动态单元图仍触发 500 节点拒绝，没有放宽限制。

示例 24 与版本化 red／nir 样本实际计算三个固定原型的逐项差、平方距离、负分数和 argmax，前五有效像元索引 `[0,1,2,0,0]`；距离 `[1/32,1/32,5/32]` 取首个并列，精确匹配零分数和全负分数均有效。独立 Fraction／Decimal／NumPy 参考、单波段缺测、多边形外控制及来源／波段保持通过；距离／分数／索引图 113／125／136 节点，网络入口尝试 0。这是固定原型选择，没有注册 Image.classify 或声称分类训练已完成。

Linux Python **1456 passed／7 skipped**、前端 **11 passed**、TypeScript／构建通过，新增 28 项：argmax 数值／参数 22、工作流 3、SDK 一致性新增 3（总 59）。Luna max 对最终冻结的四组 84 项以 `-W error` 独立重跑通过；另以形状 `(2,3,2)` 的并列最大值手算核对 `[0,2,1]`，实际 357 节点且来源／元数据保持。初始测试的 fixture 未导入、NumPy 不支持的断言参数、SDK ValueRef 解析，以及提前触发的 bundle／解码器拒绝路径均修正为正确参考；生产限制未放宽。原 50 探针和完整 Python 目录字节不变，报告 `reports/gee-python-wave19.json` 单列 S／C／静态或采样 N 和未运行 E／G。整体目标继续。

## 初始交接状态（历史）

- 仓库：https://github.com/JamesLinYJ/local-ee
- 已发布基线：`d774f01af26dc002d3193fdd2c4c7f035c277b2b`，包括 `130b527` 的 Python 官方客户端、常量波段及 Float64 归约，以及 Python 地图事件前端。该基线的 GitHub `python`、`frontend` 检查通过。
- 初次交接使用 `handoff/gee-python-cloud-20261021`。其内容已被后续 main 实现取代；现在续作必须获取远端最新 main，不能把旧交接分支当作最新开发状态。
- 交接时已无存活的开发子 agent；不需要等待旧 agent 句柄。本机工作台服务不是这些开发子任务的一部分。

## 已有实现和证据

官方 `earthengine-api` 1.7.49 固定到 Google 上游提交 `e189e4b89e785019ea5642ea8e80cb644749cd4a`，与 JS 相同。Python 运行器保留 openEO `connection`，注入本地 `ee` 和 `Map`。官方 SDK 构造表达式；共享编译器负责实际支持的算法。禁止默认 Google OAuth、项目发现与公网回退。

- 模块：`gee/ee_python_{client,transport,tasks,exports,map}.py`，每个约 150–200 行。
- 后端：`gee/services/ee.py`、`ee_events.py`、`ee_idempotency.py`，父脚本权限校验、地图事件预算、数据库持久化请求去重。
- 本机数据库迁移 v4 仅新增请求唯一索引；升级前已备份，本机记录数量保持不变。
- 报告：`reports/gee-python-client.json`、`reports/gee-constant-wave5.json`。
- 原生 macOS 实测：Python SDK 的值读取、地图、Task 启停／状态／列表、GeoTIFF／区域 CSV 下载、四路相同请求去重；Edge 示例运行并显示地图和下载入口。
- 常量／日期波段：14 个用例、18 个输出波段，独立 NumPy/Rasterio 比较为零掩膜和数值差异；没有 Google 同数据比较。
- 交接时应用测试为 412 passed / 3 skipped（另有真实内核／SPI 检查）；前端 11 项测试、TypeScript、构建通过。

## 初始交接问题及当前状态

1. 初始 50 项草稿为 38 编译通过／12 拒绝，旧硬编码网络计数不构成证据。现已拆分模块、补专用重复性／漂移测试与 deny/count 守卫，v2 仍保留原表达式，并分开标注未运行的 E/N/G。
2. Python 命名 GeoJSON CRS 引起的 unhashable dict 已修复，四个相关原探针通过；只接受明确的有限二维 EPSG:4326 平面范围，其他语义拒绝或列为未验证。
3. Filter.notNull 已补专用回归、能力登记与预算；本地平面属性名 S/C 验证，无 Google 对照。
4. Dictionary 空 keys／缺键和 List.sequence count 已补；有限元数据 Join、静态矩阵也已补。栅格数组／回归、分类器、空间／时间度量 Join、邻域／高级时序仍有实质缺口。
5. `reports/gee-python-api-inventory.json` 已生成 991 项签名／2451 参数和公开 Python 绑定目录；列出方法不等于实现所有重载或后端算法。

## 云端起步

先读 AGENTS，再使用仓库固定依赖和 CI 命令：

```sh
python3.11 -m pip install uv==0.12.12
uv sync --frozen
.venv/bin/python -m pytest -q
cd web
npm ci
npm test
npm run build
```

使用 Python 3.11、Node 24；安装过程需要官方 GitHub 和包仓库。不要自行替换锁定的 SDK、Spark 或 Scala 版本。探针脚本作为模块运行：`.venv/bin/python -m scripts.ee_python_probes`。运行前后比较生成夹具，并为失败类型增加测试。

Linux 云端继续完成 SDK、纯编译、权限服务单测、前端和合成数值测试。本阶段不实施新的 Linux 隔离执行适配，macOS Seatbelt、ARM64 JNI 与本机真实数据验收延期；这些延期不阻断兼容开发，也不要求每批重复验收。可用的可信引擎数值测试与用户脚本运行器验收分别记录，保留已有沙箱检查；跳过或未运行项目不能标为通过。

本机账号、密钥、数据库、原始影像和私有审计目录没有上传。云端先使用版本化合成样本。不要索取／复制本机凭据，也不要恢复用户已删除的旧数据库。

## 持续实施要求

按清单完成每个真实工作流；保持 Python 优先并保留 JS。允许多个子 agent 分工，但源文件所有权不重叠，多数模块约 150–250 行，超过 400 行通常先拆分。及时清理生成的缓存、重复下载和构建副本，保留必要证据。

用户授权直接 push，不需要 PR。保护 main 的规则仍有效：先在验证分支对精确提交取得 `python`／`frontend` 成功，再快进 main，删除临时验证分支；不强推、不绕过保护。没有远端写权限时保留可审查的提交／补丁并准确报告，不把未推送说成已发布。


## 第二十批按键排序与逐类指标

2026-10-23 本机同步已发布 main `ce8362dc6c3698219eae9fccd8430ab124a2ec35` 后继续，未重复旧交接缺口。补 Array.sort／Image.arraySort，真实稳定升序置换整个切片，值与键完整掩膜合取，栅格显式 Float32、图／工作预算保持。四景合成质量筛选将 NDVI／观测天数成对排序，覆盖闰年、同日两景、并列、缺失键／反射率和 bbox 内多边形外样点；独立 Fraction 参考为 7/12 与 1/4。

新增有限 consumersAccuracy／producersAccuracy／fscore，保留训练和独立验证表链路。每类向量 rank1 Float64、Fβ 的实际行 recall 解释为明确本地政策，未宣称 Google shape／dtype 等价。Luna max 独立复审发现 Fβ 少计第二次矩阵扫描，已加收费和 64×64 边界回归；复审 101 项通过并确认关闭。

最终 macOS ARM64 可移植 Python 1535 passed／3 skipped（另排除 4 项原生测试）、前端 11 passed、TypeScript／临时目录构建通过。初次全套 4 项原生失败源于当前执行权限拒绝 sandbox-exec／进程枚举，未放宽隔离或算通过；按阶段继续延期原生／真实数据验收。50 项探针仍为 45 编译／5 拒绝，完整固定 Python 目录重复生成字节相同；64 项 Python/JS SDK 一致性回归通过。报告 `reports/gee-python-wave20.json` 区分 S／C／静态或采样 N、未运行 E／G。账号／科研数据和 `.native` 配置未修改，未部署本批到运行服务。

## 第二十一批最小距离度量

2026-10-23 以已发布 main `77ee87d54071d0406b75f27cff593d4e0417c7dd` 为基线，扩展静态 minimumDistance 的 Manhattan 与 cosine 光谱角，保留 Euclidean、kNearest=1／CLASSIFICATION 及所有既有预算。真实类均值训练、独立要素预测、训练／验证混淆矩阵与逐类指标串联在示例 26 和版本化夹具中；三种度量的验证准确率分别为 1/2、5/6、2/3，不用完美训练表现掩盖独立误差。

cosine 先保留点积符号，再用精确有理数交叉乘积排名，不先转换 Float64 范数或 acos；独立 1600 位 Decimal 归一化参考覆盖负方向、极值、次正规输入、相近方向和正比例缩放。零范数查询／类中心在预测时拒绝，等距继续拒绝；这些属于尚无 Google 对照的明确本地政策。审查期间发现构造器原先验证 metric 却仍保存默认值，现已修复并增加 IR 保留和实际不同预测的回归。

本机 ARM64 可移植 Python 1583 passed／3 skipped，另排除 4 项原生测试，本批未重跑；前端 11 passed、TypeScript／临时构建通过，未部署。固定 50 探针不变，完整 API 清单字节重现，Python／JS SDK 一致性增至 65 项。报告 `reports/gee-python-wave21.json` 记录 S／C／独立静态 N，E／G 未运行；账号、数据与 `.native` 未改。Mahalanobis、k>1、其他模式、采样／Image.classify 和内联分类要素 CSV 任务导出仍待实现，后续从远端最新 main 核对再继续，不能停留在旧交接分支。

## 第二十二批内联表格 CSV

2026-10-23 以已发布 main `e9b3b34c3489eb87d7c4454071577ab5824319c9` 为基线，接通内联 FeatureCollection／分类要素的 Export.table.toDrive(CSV)。复用现有持久任务、身份／父脚本、去重及物理文件发布合同；新增 local_ee_table 仅接受字面输入直连 CSV sink，两节点数据图不允许混合栅格／回调。engine/native_run.py 在原有受限批任务入口直接写 CSV，不启动 JVM，也不更换隔离适配器。原有区域 CSV／GeoTrellis 分支保持。

新增示例 27 真实训练／预测后导出三个六行 CSV；Python Task 与 JS runner 对象／位置参数通过可信夹具实际写出、最终化并由 Jobs reader 读回。该夹具替代数据库、队列、传输和 NativeTask 启动，不是实际 HTTP／PostgreSQL／Seatbelt／浏览器验收。数据、账号、原生配置／进程和锁定依赖未改，未部署本批。CRS／bbox 包含性、保留数据字段、CSV 引号／内部换行／大字段、根目录别名及子 symlink 拒绝均有回归；默认列／null／嵌套单元属于明确本地政策，跨反经线 bbox 和其他格式仍拒绝。

最终 ARM64 可移植 Python 1685 passed／3 skipped，另排除 4 项原生测试、未重跑；前端 11、TypeScript／临时构建通过。独立只读复核 113 项通过。50 探针保持 45 编译／5 拒绝，完整 991 项 Python 目录字节重现，65 项 Python／JS SDK 一致性继续通过。审计生成器首次在 macOS 默认 /var 临时根别名上错误拒绝，现经共享物理解析器后比较规范路径，独立重现已成功。详见 reports/gee-python-wave22.json，栅格 E／Google G／生产与私有真实数据验收继续单列。

## 第二十三批：影像分类与最新起点

2026-10-23 以已发布 main `d8be821ee1dbe1a434545724c1dee984aa81309d` 为基线，完成已训练 minimumDistance 的有限 Image.classify：schema 按名称选波段／排列，精确分数类中心进入专用 GeoTrellis 内核，输出整数类别与NoData。三种度量、精确1/3、额外波段掩膜独立、单景／多景map、元数据与后续组合有合成图N；Map与导出表达式可编译，但本批未提交真实原生任务。

实际 standalone tile 内核已通过141预测／掩膜／错误控制、16非法模型和9binary64解码参考，未启动SparkContext。启用可信内核测试后Python1751 passed／3 skipped，另排除4项原生测试；前端11／构建通过，Python／JS SDK图一致性为68。云端无本机JDK／JAR锁时可跳过该显式opt-in内核测试，不能算通过；便携兼容层可以继续。完整Spark cube、隔离运行器／浏览器、部署／真实数据和Google对照未验收；锁、账号、数据、运行配置未改。详见`reports/gee-python-wave23.json`。

**新任务现在必须从远端最新main开始**，读取最新GOAL、清单及wave报告。旧handoff分支只保留历史，不再作为续作起点；本机未提交改动不会自动进入云端环境。Python完整兼容、采样／其他分类器、高级时序和完整运行验收仍有实质工作，目标保持进行中。


## 第二十四批：影像取样、动态模型与样本任务

从最新 main 续作；本批基线为 `57ce41f813d46cf2012c2831f63667d05bd2f9f1`。新增有限 sampleRegions 的实际 native sampler、规范规格／类型边界、样本 CSV／getInfo 和真实样本运行时 minimumDistance 训练。训练子图保留固定场景和独立网格，不受目标 map／export 影响；输出像元和训练输入分别计费。空样本如实为空，dry-run 只携带 schema／traces，不生成假数据。语法与限制见 `docs/gee-python/sampling.md`。

便携 Python **1882 passed／3 skipped**，另排除 4 项原生测试；前端 **11 passed**／TypeScript／临时目录构建通过。启用两个明确 opt-in 的可信 JVM 内核，分别核对取样几何／掩膜／Float64 和分类数值，未启动 SparkContext。云端缺少本机锁定 JDK／JAR 时这些测试跳过，不能记为通过。Python／JS 官方客户端图一致性增至 **72**，原 50 定向探针仍为 45 编译／5 拒绝；完整 Python API 清单字节相同。入口清单 273／991 只表示 handler 名称，不能代替参数及计算兼容率。

独立审查确认并修复 pending 样本表的上游 SaveResult dry-run、实际网格分辨率／米制 CRS 校验，以及训练范围污染输出预算。`reports/gee-python-wave24.json` 分开记录 S／C／N、真实 tile 组件与未运行的完整 E／G。没有部署、服务重启或改变隔离、账号、数据与 `.native`；整体目标继续。


## 第二十五批：标签准备与真实样本筛选

本批基线 `8b3ba4cd29f22c046938f5a382d5fe3da5534716`。新增 Image.remap 的真实 Float64 精确查找内核、有限 Filter.expression parser 和取样后 filter／无排序 limit。保留原 sample spec／schema／顺序／ID；条件可读 system:index，副本不写进结果属性。最多16操作，原规格／前序操作复核、表复制、筛选及模型训练累计共享50000工作预算，在复制／构造前拒绝超限。原 sampler 上限仍先执行。固定训练来源／网格与目标输出预算分开，literal-only CSV 图仍封闭。

示例30与原始标签网格夹具独立验证15有效样本→14非空→11条件→8训练行，类均值 red/nir 为 `[6/5,17/5]` 与 `[11/3,20/3]`，保留重叠权重和目标ROI外训练。Python/JS5条新图一致性全部通过，累计77；45/50原定向脚本编译及完整Python目录字节保持。便携Python **2068 passed／3 skipped**（另排除4项原生测试），前端11／TypeScript／临时构建通过。Remap6正向／23非法spec／3有效Infinity拒绝，以及已有取样／分类实际tile内核通过，均无SparkContext。云端缺少锁定JVM依赖时须按opt-in明确跳过，不算实际内核通过。

独立复审发现并修复system:index过滤、谓词语义深度与wire容器深度错配，以及预算未覆盖复核／复制的问题。报告 `reports/gee-python-wave25.json` 分开记录S/C/N和未运行完整E/G。没有部署或修改账号／数据／运行配置／隔离。Smile依赖不在锁中，未用SparkRF替代；后续路线与许可证版本依据见 `docs/gee-python/random-forest-roadmap.md`，不能把本批当作随机森林完成。继续从远端最新main，不从旧handoff起点恢复。

## 第二十六批：真实 Smile RF 与受控模型边界

基线 `2a4d8b2c691607ce30c2b14d169a6f2c18652b36`。RF独立IR、六参数、内联／采样表可信JVM训练、影像预测与schema/CLASSIFICATION；训练／目标来源网格分离。模型只接RF predictor，嵌套ref与callback scope也检查，标量／向量不能当栅格。复制计费覆盖完整嵌套结构的保守上界，原表操作50000不变。RF按1000×8实测分开150000对象工作与3MB wire字节，prior table work仍须0..50000；原compiler/MD50000、单JSON1MB和其他预算保持。省略inputProperties依赖band_order的重载尚未支持，不从sampleRegions猜schema。

完整便携回归2293 passed／3 skipped，另排除4项延期原生测试；前端11／TS／临时构建通过。原50探针仍45通过／5拒绝，唯RF构造器直接JSON结果的拒绝原因改变并审阅；完整PythonAPI目录字节相同。新增3项Python/JS图一致性为S/C。四个opt-in真实JVM tile组件包括RF1000行×8特征×100树控制；没有SparkContext、完整batch/sandbox/browser或Google证据。最终Unicode扫描器改按码点限制，129／256码点的schema及class_property实际train→predict通过，257拒绝；变更后79项定向复核通过，未重复宽套件，原full-run证据保留。

Smile1.5.3四JAR与复用SLF4J固定于`deploy/smile-rf-lock.json`，`scripts/build_smile_rf_adapter.py`只用显式本地依赖、构建到专属work scratch并出独立SPI/manifest；不下载、不安装到.native。原runner在SparkContext前验证可选包，缺包保留旧行为；部分包／摘要／重复SLF4J／未知classpath项失败。新增sandbox只读精确文件为`.native/engine-lock.json`、`deploy/smile-rf-lock.json`、`scripts/build_smile_rf_adapter.py`，未开放整个目录或外网。云端缺少锁定JDK/JAR时RF kernel保持opt-in skip，不记作通过。继续从最新main；RF explain／随机列／表分类／动态矩阵、模型保存和完整运行部署仍待做。


## 第三十二批接续：真实随机森林解释

新增`Classifier.explain`的封闭三字段字典与有界get/keys/contains/values投影，官方Python／JS图一致。实际Smile importance/tree count/rawOOB进入独立runtime_explanation JSON任务，原矩阵数值边界、父脚本／用户权限和物理文件发布仍保留。图与运行时保持RF150000／3MB预充；不含解释对象的表达式跳过新增扫描，含对象时所有参数容器迭代检查并计费，循环和共享DAG安全。静态If／内联Collection.iterate可选同一个直接最终结果，不允许进入后端运行时回调。

冻结源码2788 passed／3 skipped（排除4项延期原生测试），六可信组件与前端11／类型／临时构建通过；两项后续静态控制流精确图测试通过，生产代码未再改。实际三树独立Gini参考 `[0,1.5]`／树数3／OOB0及JSON读回通过；它不是任意森林或Google／真实数据能力证明。首次全回归2772通过／7失败／3跳过暴露普通列表与表格重复扫描回归，根因修复后原样本和预算通过。见 `reports/gee-python-wave32.json`、`docs/gee-python/rf-explanation.md`、示例37。入口279／991（28.15%）只统计名称；完整兼容目标继续。

保留较大内联训练与投影链的50000编译工作上限，可能先于1000行上限触发。OOB沿用Smile1.5.3无票时也可能返回0的策略；无树文本／模型保存／通用动态数学／CSV或栅格输出。未部署，无完整Spark／沙箱任务／HTTP浏览器／Google同数据验收。继续从最新main，优先完成真实工作流依赖而非单纯增加名称；不运行容器或恢复虚拟机，用户数据和现有账号保持原状。


## 第三十三批接续：按族批量静态API

五组Luna/max并行、父任务集中集成Number25／Array36／List18／Dictionary10／String9，共98个新增名称，全部实际有限静态计算；官方单列别名包含在入口统计内。冻结便携2989 passed／9 skipped（排除4项延期原生测试），前端11／类型／临时构建通过；示例38的10个组合输出有独立预期及官方Python／JS结果一致性，网络尝试0。共享工作50000、rank8／10000单元／1MB输出等预算不提高。

新List操作显式启用递归精确整数检查；旧static_equal宽整数比较／contains／distinct政策保留。初次全回归2986通过／9跳过，独立源审查仍找到此边界缺口，修复和新增边界测试后统一复验通过。其余局部旋转／字典碰撞／轴／Unicode／JSON格式／浮点政策与Google尚无对照。见`reports/gee-python-wave33.json`、`docs/gee-python/static-families.md`和示例38。

当前名称377／991（38.04%）不是完整GEE语义覆盖率；新静态函数不自动支持同名Image算法。只改编译器及帮助文本，本批不重建未变化JVM，无新栅格／Spark／沙箱任务／浏览器／部署验收。邻域source reconnaissance保留于本地audit，已找到MultibandFocalOperation的halo／逐波段路线，但focal／Kernel仍未实现，后续需真实接缝／时间／掩膜验证。继续批量按真实项目依赖推进，保持目标active，沿用protected-main精确SHA检查后directpush，及时清理本批闲置scratch。
