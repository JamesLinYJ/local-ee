# 云端开发交接

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

## 获取正确状态

- 仓库：https://github.com/JamesLinYJ/local-ee
- 已发布基线：`d774f01af26dc002d3193fdd2c4c7f035c277b2b`，包括 `130b527` 的 Python 官方客户端、常量波段及 Float64 归约，以及 Python 地图事件前端。该基线的 GitHub `python`、`frontend` 检查通过。
- 从 `handoff/gee-python-cloud-20261021` 分支继续；这个分支包含交接时尚未完成的 Python 探针和 notNull 改动。先检查分支最新提交，不要只克隆旧 main。
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
