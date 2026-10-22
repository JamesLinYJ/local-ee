# GEE Python 兼容清单

状态：2026-10-22，第十六批持续实施，整体兼容目标尚未完成。

第十六批 [验证报告](../../reports/gee-python-wave16.json)：Linux Python **1338 passed／7 skipped**，前端 **11 passed**、TypeScript 与构建通过；上一批为 [1303 passed／7 skipped](../../reports/gee-python-wave15.json)，本批增加 35 项通过回归。7 项平台／配置跳过为 3 项 opt-in JVM/Spark 检查及 4 项 macOS Seatbelt 检查；它们不构成原生平台验收。

S＝官方客户端实际序列化；C＝本地编译；E＝实际栅格引擎；N＝独立数值基准；G＝Google 同数据对照。静态数值求值和合成图测试分别说明，不能标成原生栅格 E。固定的 991 项签名、方法可见数量和定向探针计数均不能换算为全 API 兼容百分比。

当前阶段按用户要求暂缓 Linux 隔离执行、macOS／ARM64 和本机真实数据验收，优先完成 Python API／参数／计算语义，再推进 JS。新增能力继续用版本化合成样本、独立数值参考及已有便携测试验证；延期项目不是本阶段前置条件，现有运行器与沙箱检查保留。

已有项目与可复用边界见 [生态核对](ecosystem.md)：本地脚本宿主、Google 客户端封装、独立本地计算后端与完整 EE 服务端兼容分别核对，不据项目名称或一次检索判断其兼容范围。

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
- [x] 内联表格 reduceColumns 及有界 List.reduce 的无权 linearFit／linearRegression，保留矩阵类型及每响应残差 RMS；闭式系数／残差参考与合成预测示例。
- [x] Number.format 的有界十进制子集，以及 String 数值构造、cat／length／compareTo 和分配前预算。
- [x] 唯一 maxDifference 与标量条件的 And 组合；最近前／后观测筛选、inner 匹配对和 Feature.map → ImageCollection 计算链路。
- [x] 有限静态 Array 的逐元素算术、slice／project／repeat／cat、单输出归约与累积、对称特征分解及 Cholesky；闭式 PCA 协方差、投影和重建验证。
- [x] 固定形状单数组波段的 Image.toArray、布局、矩阵乘法与单输出归约；静态 PCA 基投影到本地影像像素图，独立核对分量、重建和整体掩膜。
- [x] 有限 ImageCollection.reduce(linearFit) 逐像元斜率／截距，完整行缺测删除、中心化 OLS、低样本／退化掩膜和同日多景身份；时间属性串联趋势预测，独立 SVD 参考。
- [x] 有界静态 ConfusionMatrix 的构造／array／order／accuracy／kappa、内联 FeatureCollection.errorMatrix；显式标签顺序与有效行筛选串联分类评估，独立频数／机会一致概率参考。采样及分类器训练／预测不在该子集中。
- [x] 有界 List 配对／转置／展开／重复／置换，以及单输出归约和 List.reduce(linearFit／linearRegression) 多输入行；列列表构造二次设计、双响应系数／RMS 和预测的闭式／残差正交性参考。
- [x] 有限欧式 minimumDistance 的实际类均值训练、唯一最近类预测、schema／默认模式、内联要素分类及真实重代入混淆矩阵；独立训练／验证样本、均值／距离和误差指标参考。
- [x] 有限栅格 linearRegression 的过原点／单位截距模型、1..4 响应、联合完整行、系数／RMS 数组；有限多数组波段选择／元数据，双响应分字段物化和独立 SVD／空间掩膜参考。
- [x] 延迟单波段维度／改名元数据，保留数值与源／掩膜／类型边界；共享表达式标签、完整四系数／双响应预测、同日／重复观测及超限控制。
- [x] 静态方阵 QR／LU／SVD 真实分解与因子字典组合；部分选主元、退化正交分解、资源预充，以及合成光谱混合／噪声丰度的独立分数参考。
- [x] 单数组波段的真实 toFloat，以及静态满列秩设计的有限 Image.matrixSolve；栅格多响应、整体缺测掩膜、显式精度和预算拒绝；合成光谱估计／重建／残差的独立分数参考。
- [x] 有限 ImageCollection.toArrayPerBand 的定长逐波段堆叠、静态 Image.arrayReshape 和 Number.sin／cos；集合日期驱动的谐波设计与栅格最小二乘链路，参数与数值边界见下文。
- [x] 有限静态 Number／Array.hypot／atan2，以及由既有像素算子计算的 Image.hypot；独立高精度范数／方向角参考，串联谐波系数的真实振幅输出，轴约定与 Float32 溢出边界明确登记。
- [x] 单数组 Image.arrayCat／arrayRepeat 的真实轴布局、有效常量 Image 重复次数、共同掩膜和预算拒绝；双独立响应最小二乘工作流的系数／拟合／残差与 Fraction／SVD 参考一致。
- [ ] 每一签名／参数组合的 S／C、适用的独立 N，以及负向、缺测、边界验收；E 按现有环境可用条件单独记录。
- [ ] 动态形状、其余多数组波段运算和 Image.array*、通用设计矩阵的逐像元回归、采样／图像分类／其他分类器及模式、矢量／空间和多重／歧义度量 Join、邻域及高级时序。
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
| 静态行回归 | S/C 与独立 N；表格 reduceColumns／List.reduce 的 linearFit、linearRegression，多响应系数／RMS；缺失／null 行跳过；秩不足／n<=numX 返回 null | <=1000 行、<=32 个输入列，表格只支持平面属性选择器，List 要求精确行宽；共享预算、无权重；通用栅格 linearRegression 与 G 未覆盖 |
| 栅格 linearFit | S/C；完整 x/y 行、中心化两遍 OLS，输出 scale／offset；独立闭式与 NumPy SVD N 核对系数、重复景权重、缺测、空间范围及目标日期预测 | 1..8 帧，恰两个同名同序标量波段；binary NoData 掩膜，n<2／x 方差为零则两个输出均掩膜；parallelScale 仅 1，仍受 Float32 callback／工作／图预算约束；无实际 E/G，非通用栅格 linearRegression |
| 有限分类评估 | S/C 与独立标签频数 N；静态 ConfusionMatrix 构造、array／order／accuracy／kappa；内联 errorMatrix 保留 actual 行／predicted 列及显式顺序 | <=64 类／4096 单元，非负整数 Array 计数总和 <=2^53、<=1000 完整标签行，共享预算；原始 List／浮点计数 Array、缺失／null、零分母、直接对象 JSON、Feature 属性对象与逐类指标拒绝；无采样／分类器或 E/G |
| 有限 List 布局／归约 | S/C 与独立静态 N；zip／unzip 截短、flatten 只展开 List、repeat／reverse／set／swap 保留 typed 原子；单输出值、多输出回归字典／typed Array | 布局 <=10000 顶层值、flatten 深度 96，reduce <=1000 行／32 回归列，共享预算；严格下标边界，非默认 reducer 组合／权重拒绝；空值政策见下文，无 E/G |
| 静态欧式最小距离 | S/C 与独立 N；真实类均值、唯一最近类、FeatureCollection.classify、schema 和训练重代入矩阵 | k=1／CLASSIFICATION、训练 1..1000 行、显式 1..8 平面属性、类别 0..63、subsampling=1／seed=0，共享预算；精确 binary64 有理数政策，等距和属性碰撞拒绝，无采样／图像／其他分类器或 G |
| 有限栅格 linearRegression | S/C 与独立样点／SVD N；过原点或单位截距模型，多响应共用完整行，真实系数 (numX,numY) 与 RMS (numY,) | numX=1，或 numX=2 且首列证明为单位字面量；numY=1..4、1..8 同序标量帧，n>numX／非退化，RMS 按 n；parallelScale=1、Float32 callback、工作／500 节点限制，无通用设计矩阵／E/G |
| Number／String | S/C；%s／%d／%f、有限符号及填充；数值 String 构造与三个基础方法；指数拼接预算负控 | Number 按 Python 最短十进制拼写半入舍入，String 按 Python code point；科学／十六进制格式等拒绝；本地政策无 G |

List.contains／distinct 对嵌套数组使用显式的有界比较，避免 NumPy 隐式真值／广播错误。标量 int／float 按数值比较，bool 单独区分；Array 的 dtype／形状／元素比较仍是未做 Google 对照的本地策略。step 序列严格检查实际生成的 Float64 值，不向端点外扩展；例如 0、0.1、0.2 后的 0.30000000000000004 超过 end=0.3，因此省略，该舍入策略尚无 G 证据。

另有 47 项 Python／JS 固定 SDK 实际序列化后进入共享编译器的结果一致性回归，覆盖 count 序列、Dictionary、矩阵、notNull、Join（含 inner 和复合时间条件）、几何、表格回归、要素遍历、格式化及字符串构造；包括静态数组布局／归约、特征分解、Cholesky、QR／LU／SVD 和逐元素算术，以及栅格数组投影／归约、逐像元 linearFit 计算图、混淆矩阵 Kappa、标签误差矩阵、列表布局／均值／回归、最小距离 schema／预测／训练误差矩阵、栅格 linearRegression 的过原点／截距系数与 RMS、方阵／高矩形设计的栅格 matrixSolve、集合定长数组、reshape、正余弦设计，以及静态向量范数／方向角、栅格 hypot 和轴拼接／整块重复。这是保留共享后端行为的检查，不表示已完成 JavaScript 全量兼容或 Google 数值对照。

第四批 `examples/10_GEE_python_synthetic_pca.py` 与 `tests/fixtures/ee-pca-table-v1.json` 串联有限静态表格的中心化、样本协方差、对称特征分解、投影及重建。四条二维观测的均值为 `[2,1]`，协方差为 `[[4/3,2/3],[2/3,2/3]]`，特征值为 `1±sqrt(5)/3`；闭式向量与得分按 1e-14 容差核对，重建还提供与符号选择无关的验证。S/C/N 已通过，网络入口尝试为 0；无栅格 E 或 G。

这批 Array 新增能力均受 10000 单元／每轴长度、8 轴及共享 50000 步预算限制。二元算术只接受同形数组，除零返回零，负数平方根和非有限结果拒绝。slice 接受负偏移和正步长，可产生空轴；project 仅接受升序不重复轴，删除轴长度必须恰为 1。repeat 拼接整个数组；cat 需要类型化 Array，尚不支持原始嵌套列表的强制转换。reduce 支持 sum／mean／min／max／count／median／sampleStdDev，归约轴保留长度 1；fieldAxis、多输出归约、空输入及少于两个值的样本标准差明确拒绝。accum 限 sum／min／max，浮点前缀按顺序相加；显式 PixelType 和完整广播仍待实现。

eigen 限非空二维实对称矩阵，Cholesky 另需正定，输出下三角 L；determinant 限方阵，trace／diagonal 支持矩形。eigen 按特征值降序输出行向量，每行首个最大绝对值分量取正；重根子空间沿用 LAPACK 基。该符号／重根呈现规则是尚无 Google／EJML 对照的本地政策。浮点 sum／mean／median／trace 对有限抵消使用稳定求和，必要时在有界二进制有理数域完成中间求和，避免可表示结果因中间溢出而失败；这不代表所有浮点内核具有相同的极值稳定性。

第五批 `examples/11_GEE_python_synthetic_raster_projection.py` 与 `tests/fixtures/ee-raster-projection-v1.json` 使用同一合成训练表求 PCA 基，将本地 red／nir 像素中心化、转列数组、矩阵投影并重建波段。数值参考使用闭式正交基，任一输入波段缺失时所有分量／重建波段均无效；输入来源、顺序和显式复制的时间／ID 属性也有回归。S/C/N 已通过、网络入口尝试为 0；N 使用独立测试图求值器，实际栅格引擎 E 与 Google G 未运行。

栅格数组在编译器内部保持独立类型，只有 arrayFlatten／arrayGet／arrayLength 等标量输出进入既有后端；不将单元伪装成公开影像波段。数组常量的波段名为 constant，普通 scalar Image.toArray 输出 array；已有数组再次 toArray 保留原名，此命名政策尚无 G 对照。固定形状的 arrayReduce 支持 sum／mean／min／max／count／median／sampleStdDev；fieldAxis、多输入输出归约及单元素样本标准差拒绝。arrayProject 仅支持升序保留轴、删除轴长度恰为 1；slice/get 仅支持数值或所列纯算术常量 Image 坐标，动态／掩膜坐标拒绝，slice 产生空轴时拒绝。rank0 可经空坐标 arrayGet 取值，rank0 flatten／arrayLengths 仍拒绝。

静态 If 分支、Dictionary 缺键默认值和 Image 显式转换均保留数组影像类型；重命名、属性设置／读取／复制仍针对逻辑单波段。未支持的影像算子遇到数组类型时明确失败，类型不能泄漏为 JSON 或被当作静态真值。ImageCollection.toArray、动态数组形状、多数组波段、广播、逐像元特征分解及直接数组影像导出仍待实现。

第六批 `examples/12_GEE_python_synthetic_linear_trend.py` 从每景实际 system:time_start 求相对日数，绑定为本地网格常量、显式转为 Float32，与 signal 组成两列。linearFit 保留同日不同 ID 的每次观测，任一列 NoData 时只删除该像元的那一行；以两遍中心化 OLS 求 scale／offset，低样本或零方差输出均为 NoData。系数不继承任一原始观测日期，预测显式标注 target_time_millis 和样本版本。该接口只支持 binary NoData 模型，不宣称分数权重或完整 dtype 提升；parallelScale 非默认值明确拒绝。

`tests/fixtures/ee-raster-linear-trend-v1.json` 的四景包含两个同日观测。闭式系数分别为 `(55/19,31/19)`、`(27/14,17/7)`，第 2 日预测为 `141/19`、`44/7`；独立 numpy.linalg.lstsq 验证了参考、行数及秩。直接数值控制还覆盖重复观测对拟合权重的实际影响、常数信号、低样本、零方差和范围外的完整行删除。测试求值器在提供 grid 时真实应用源查询范围、逐景多边形和常量波段掩膜；对多边形外但原始数组有限的样本也必须掩膜。S/C/N 已通过、网络入口尝试为 0，N 为采样点求值，不能当作原生栅格 E、分数边界权重或 Google G。

版本化样本 `tests/fixtures/ee-table-workflow-v1.json` 和可运行示例 `examples/08_GEE_python_synthetic_regression.py` 串联有效值筛选、表格 OLS、矩阵预测和格式化。手算系数为 0.5／2.5、残差 RMS 为 sqrt(0.5)、第 3 日预测为 8。它是静态合成表格工作流，不是实际影像、栅格 E 或 Google 对照。

第七批 `examples/13_GEE_python_synthetic_classification_validation.py` 和 `ee-classification-validation-v1.json` 用显式 [30,10,20] 顺序评估预测标签。notNull 显式去掉 3 条缺失／null 行，18 条完整行中 actual=99 的一行被类别表排除，17 条计入行得到 `[[4,0,1],[0,5,1],[1,2,3]]`。总体准确率 12/17、Kappa 107/192，独立参考另从标签频数计算机会一致概率，不借用实现的矩阵归约。

ConfusionMatrix 只接受 typed integer Array、方阵及非负计数；最多 64 类／4096 单元，总和 <=2^53，整数中间计算避免计数乘积溢出。显式顺序为唯一整数标签，保留负数／稀疏顺序；[] 仅匹配 0×0。errorMatrix 默认使用 0..max（含空档），显式顺序仅计入两列都存在于顺序表的行，空集合必须给顺序；完整整数值 float 标签可转成 int。缺失／null 不自动跳过，先显式筛选。零分母指标拒绝，不伪造 0；这些边界尚无 G 对照。

原始嵌套 List 虽可被 SDK 序列化，本地构造仍要求 typed Array；浮点计数 dtype、显式 Array PixelType、producersAccuracy／consumersAccuracy／fscore 和直接／嵌套矩阵对象 JSON 仍拒绝，须选 array／order／accuracy／kappa。内部矩阵可经 If／Dictionary.get 再调用方法，但尚不能存入 Feature 属性。独立 Luna max 复审未发现声明子集内可复现缺陷；S/C/静态 N 通过，网络入口尝试 0，不涉及栅格 E、G 或采样／分类器训练预测。

第三批的 `tests/fixtures/ee-temporal-interpolation-v1.json` 与 `examples/09_GEE_python_temporal_interpolation.py` 串联最近前／后观测、毫秒权重及像素插值；合成信号的手算输出为 `[6, masked, masked]`，保留目标时间及两个邻居的有效像素交集。inner 匹配后组合两个来源的波段也有独立来源／掩膜参考。示例函数需要调用方提供实际本地集合，测试使用明确版本化的合成目录／数组；本轮尚未运行实际栅格引擎。

度量 Join 仅在请求 measureKey／saveBest 时要求恰好一个 maxDifference，且它只能直接出现或位于 And 下。其余标量逻辑可组合；不请求度量的布尔 Or／Not／多条件保留原有筛选行为。inner 的 measureKey 位于匹配对 Feature 上，saveFirst／saveAll／saveBest 的 measureKey 位于匹配 Image 上；默认 inner 键为 primary／secondary，自定义键必须互异，避免覆盖匹配来源。

内联要素的有序属性比较将缺失／null 视为 UNKNOWN；Not 保留 UNKNOWN，And／Or 使用三值逻辑，最终 UNKNOWN 不匹配。这能保留 SDK 的 gte／lte → Not(lt／gt) 序列化语义；该空值政策尚无 Google 对照。涉及缺失／null 的 equality 及复杂对象比较明确拒绝，不能据此宣称完整 Filter 兼容。递归谓词、成员扫描和字符串比较共享编译预算。

整个公开输出共享对象数、深度和 1 MB 编码预算，字符串转义和重复匹配属性在转换期间计费，避免先分配巨大 JSON 再拒绝。静态数组和匹配影像在编译器内部保留类型，到公开边界才转换为有限 JSON；不公开 Pixel IR 或磁盘路径。

## 列表设计矩阵与回归

第八批 `examples/14_GEE_python_list_polynomial_regression.py` 与版本化 `ee-list-regression-v1.json` 用 repeat／unzip 组装 1/x/x² 和两个响应列，List.reduce(linearRegression(3,2)) 输出真实 typed 系数／RMS，继续进入矩阵预测。独立构造残差 e=[-1,3,-3,1,0,0]，与全部设计列正交，第二响应残差为 2e；系数 `[[1,-2],[2,0.25],[-0.5,1.5]]`、RMS sqrt(10/3)／sqrt(40/3)、x=4 预测 `[1,23]` 均有校核。工作流先验证列长度相同，不能让 unzip 的正常截短掩盖观测错配。

List.reduce 限 1000 行，回归每行恰 numX+numY 个输入、最多 32 列，无权；null 行／含 null 的行剔除，其他非空字段即使处于不完整行也须合法。回归共用表格数值内核，低样本／秩不足返回具名 null 输出。标量 count 计任意非 null 值，first/last 保留第一个／最后一个非 null 的类型；其余数值归约支持 sum／mean／min／max／median／sampleStdDev，有限整数域 <=2^53。空／全 null 的 sum/count=0、其余为空以及有效值不足两个的 sampleStdDev=null，均是尚无 G 对照的明确本地边界政策，不是完整 Reducer 合同。

List 布局每个顶层输入／输出最多 10000 值，flatten 递归深度 96，只展开 List、保留 Array／Image 等原子值；工作、扫描和公开 JSON 预算另行生效，达到大小上限不保证组合运算一定在工作预算内。repeat count 0..10000；set/swap 负下标从末尾计，越界拒绝且不修改源。SDK 的 repeat(None,0/1) 会省略必需 value，已分别记录 S 可序列化与 C 缺参拒绝，未猜测该 wire form 的服务端默认值。

## 有限最小距离训练与验证

第九批 `examples/15_GEE_python_minimum_distance_validation.py` 和 `ee-minimum-distance-v1.json` 使用分离的训练／验证行。未归一化类均值为 `(2,2/3)`、`(7,2/3)`，训练中一个离群点会预测为另一类，证明不是以最近训练点代替类均值。训练准确率 5/6，独立验证预测 `[1,3,3,1,3]`，按 [3,1] 计数 `[[2,1],[1,1]]`，准确率 3/5、Kappa 1/6。独立 NumPy 均值／距离和手算指标校核已通过，网络入口尝试 0。

minimumDistance 仅 Euclidean、kNearest=1、CLASSIFICATION；显式唯一平面 schema 1..8，完整有限数值要素 1..1000，类别为 0..63 整数，subsampling=1／seed=0。几何按官方训练描述忽略；预测按名称读取属性，不依赖字典顺序。精确 Fraction 保留 binary64 输入并计算类均值／平方距离，任何等距最近类明确拒绝；这一本地数值政策不等于已验证 Google／Smile 的浮点累加策略。共享工作上限仍生效，1000×8 的组合可能因预算拒绝。

模型不可变，If／Dictionary.get 再包装后可用；未训练 schema 为 null。要素分类保留属性／几何／ID、拒绝输出名碰撞，训练混淆矩阵用真实重代入预测、轴为 0..max 类别并保留空档。直接／嵌套模型 JSON、模型真值、Image.classify、其他 metrics／k／modes 和自动 band_order schema／随机子采样仍拒绝；没有采样、栅格 E、随机森林或 G 的实现声明。

## 有限栅格多响应回归

第十批 `examples/16_GEE_python_raster_multiresponse_regression.py` 与 `ee-raster-regression-v1.json` 从同一模型分别物化两个响应的系数、RMS 和预测，共六条有效图路径（418／497／424 节点各两条）。原完整系数、完整 RMS、完整预测组合超过现有 500 节点；不能将这些超限组合写成通过，也不降低联合缺测语义。pixel0 的第一响应 offset=7/10、scale=11/5、RMS=sqrt(9/20)，第二响应 offset=5、scale=2、RMS=0。pixel1 第二响应缺一行，两个响应一起删行，第一响应变为 offset=17/14、scale=29/14、RMS=sqrt(3/14)，x=2 的预测为 75/14。三个掩膜位置分别为常数 x 秩不足、n=numX 和实际景界内仅两行；最后一处在所有 bbox 内但在两景梯形外。独立 numpy.linalg.lstsq／样点几何求值已通过，网络入口尝试 0，无 E/G。

numX=1 为过原点，numX=2 首列必须可证明为数字字面量 1，允许现有 cast／on_grid／reduce_t(first) 包装，原始像素掩膜仍参与共同完整行；其他设计矩阵拒绝。输出 n<=numX 或退化时系数与 RMS 一起掩膜；RMS 按残差平方和除以 n，不是自由度校正标准差。parallelScale 仅 1、binary NoData 和 Float32 callback 限制保留。最大帧数／维度分别有边界控制，但受图预算约束，不能保证最大配置的组合。

有限多数组容器为 1..8 逻辑数组波段、总 64 cells、共享元数据来源；只能精确名称／非负索引选择、rename 与现有元数据方法。先选一个数组再 flatten／get；真正 Image.cast、bundle 通用数组算术、混合 scalar／array bands、直接输出／导出以及 regex／重复 selectors 仍拒绝。内部 If／Dictionary 保留类型，不能转成静态真值或虚构服务器 JSON。

第十一批在下一真实 cube 进程之前延迟物化单波段标签，不跨越 callback、mask、cast 或时间边界。同一六条图降至 333／394／337 节点各两条，数值与 NoData 样点保持一致；完整四系数现在为 405 节点，双响应预测为 413，独立 SVD 和同日／重复行权重测试通过。完整双 RMS 与八字段组合仍明确超过 500，不能写成通过。共享 DAG 的不同输出名／操作数位置和 JSON／引用边界另有专用回归，见 [第十一批报告](../../reports/gee-python-wave11.json)。

## 静态方阵分解与合成解混

第十二批仅对非空静态方阵实现 `Array.matrixQRDecomposition(array)`、`matrixLUDecomposition(array)`、`matrixSingularValueDecomposition(array)`。所有因子均为 n×n、有限且只读的 typed Array；QR 返回 `{Q,R}`，LU 返回 `{L,U,P}` 且 P×A=L×U，SVD 返回 `{U,S,V}` 且 A=U×S×Vᵀ。QR／SVD 对秩亏／零矩阵验证正交性与重建，不固定符号或重复值子空间基。LU 使用首个最大值部分选主元，已生成的 L 列随行一起交换；计算零主元明确拒绝，不用容差伪造秩。非有限因子、未知参数、矩形／非矩阵输入拒绝；合并输出 cells<=10000，分解前按 factor×n³+6n² 预充共享 50000 工作步，QR／LU／SVD 的 factor 分别为 4／2／8。

`examples/17_GEE_python_matrix_unmixing.py` 与 `ee-matrix-unmixing-v1.json` 用实际因子继续求解三个合成端元的四组观测，三条路径均返回实际丰度／重建。独立 Fraction 参考给出 det=9/25，含噪样本修正 `(7/360,-13/360,1/60)` 与丰度 `(151/360,131/360,13/60)`，三路在 3e-13 内通过，网络尝试 0。S/C/静态 N 已验证；不包含 `Image.unmix`、非负／和为一约束解混、栅格分解、矩形 QR／SVD 或 Google/EJML 基与数值对照。

## 有限栅格 matrixSolve

第十三批实现 `Image.matrixSolve(image1,image2)`：左 A 为静态字面量常量和可选 Float32／Double cast 链，形状 (m,n)，1<=m<=8、1<=n<=4、m>=n；右 B 为 (m,k)，1<=k<=4，可含实际来源像素。双方每个 cell 必须显式以 toFloat 结束。单数组波段的 Image.toFloat 对每个 cell 生成真实转换，保留形状、逻辑名、属性和整体掩膜；数组 toDouble、多数组 bundle cast 仍拒绝。标量 toDouble 后显式转成数组再 toFloat 是允许的精度选择，不隐式缩窄。

A 的每层 cast 都按内到外次序执行并按 Pixel 对象缓存，保留 16777217→Float32→16777216 的精度效果，共享尾链不重复求值。先预充共享工作预算，再用 NumPy Float32 输入的 `lstsq(A,I,rcond=None)` 求有限伪逆，最后生成实际逐像元乘加及 Float32 输出。NumPy 的秩判定和 callback 舍入是已注明的本地数值政策，未证明与 Google/EJML 相同。动态 A、欠定／秩亏、非有限系数／伪逆及未知／缺参明确拒绝。

总输入 <=64 cells、常量表达式 <=500 unique nodes，共享 50000 工作步和 500 进程节点上限保留；最大允许形状不保证生成图能通过。B 任意行／任意响应缺失会掩膜所有解分量，与集合回归删除不完整观测行不同。输出沿用既有有限源网格／来源及整体掩膜策略，保留左属性；不据此宣称完整全球足迹／投影语义。

示例 18 与 `ee-raster-least-squares-v1.json` 使用 A=`[[2,1],[1,2],[1,1]]`，手推伪逆为 `(1/11)[[7,-4,1],[-4,7,1]]`。含噪观测得到 `(119/220,97/220)`，残差 `(-1/44,-1/44,3/44)` 与设计列正交；丰度和为 54/55，负输入可以得到负丰度，不添加非负／和为一约束。估计／重建／残差分别为 70／97／116 节点。独立 Fraction 参考量化实际 Float32 输入后按 2e-6 容差核对，覆盖零值、负值、缺测与 bbox 内多边形外点。S/C/采样点 N 通过，网络尝试 0；这不是 Image.unmix、实际栅格 E 或 Google G。

## 定长时间数组与谐波拟合

第十四批实现 `ImageCollection.toArrayPerBand(collection,axis=0,dropMasked=false)`，限 1..8 帧、1..8 个同名同序唯一标量波段、总 64 cells。每个波段沿集合顺序组成独立 (frames,) 数组，重复观测保留；该数组的有效掩膜是该波段所有帧的合取，另一波段缺测不污染它。输出沿用有限来源和各景并集范围，不继承任一景日期；多波段通过已有 typed 容器选择后继续计算。axis 只接受数值整数 0（含 wire 0.0，拒绝 bool），dropMasked 必须为 bool 且 false；true 的变长输出明确拒绝，不能冒充 ImageCollection.toArray 的逐像元有效行压缩。

`Image.arrayReshape(image,lengths,dimensions)` 仅接受单数组影像、rank-1 的常量整数 lengths 数组影像，以及 1..8 的 dimensions。lengths 掩膜须明确为有效常量；每轴 1..64，最多一个 -1 自动推断，须整除且保持输入总 cells<=64。按原 row-major cells 重解释形状，不改变数值、dtype、名称、来源或输入掩膜；rank-0 输入可以变为 [1]，输出 dimensions=0、动态／掩膜 lengths 和非法形状拒绝。共享工作预充和 500 图节点限制保持。

`Number.sin(input)`／`cos(input)` 使用弧度、有限静态 int／float（整数绝对值<=2^53）；缺参、未知参数、bool／非数值／非有限输入拒绝，运算前计入共享预算。Float64 libm 的参数约减是本地数值政策，不宣称 Google 位级等价。独立 Fraction 幂级数在 [-2,2] 核对，另有象限、signed zero、List.map 构建设计矩阵和预算负控。

示例 19 与 `ee-harmonic-time-series-v1.json` 从乱序影像元数据按时间排序，得到 day=`[0,90,180,180,270,360,450]`；两条同日观测保持各自身份。Date.difference 和 Number.sin／cos 生成周期 360 天的 7×3 设计矩阵 `[1,cos,sin]`，逐波段堆叠 → reshape → 显式 toFloat → matrixSolve，输出系数、拟合、残差及第 540 日预测。手算 AᵀA=`[[7,0,1],[0,4,0],[1,0,3]]`，含噪样点系数为 `(407/1000,1/5,121/1000)`，预测 `207/1000`；Fraction 精确残差与设计列正交，另用 Float32 输入的独立 SVD 对照，容差 2e-6。

NDVI／quality 时间数组各 122 节点，系数／拟合／残差／预测为 215／296／337／219；三个静态元数据输出另计，不当作栅格执行。测试覆盖整段缺测、另一波段独立有效、负值及 bbox 内非矩形景界外样点。网络尝试 0，S/C/采样点 N 通过，无实际 E/G；这批历史结果不包含缺测观测行压缩或完整谐波分析。后续振幅算子见下节，栅格相位仍未实现。

## 向量范数与静态方向角

第十五批 Number／Array.hypot 使用真实稳定 Float64 内核，Number／Array.atan2 按固定 SDK 的 x=left、y=right 解释调用 `atan2(right,left)`。Number 仅有限静态 int／float、整数绝对值<=2^53；Array 要求同形 typed 数组、rank<=8／cells<=10000，共享 50000 工作；复制／内核前预充，输出有限、只读，不修改输入。未实现广播，非法／缺参／未知参数明确拒绝。既有 sin／cos 迁入独立数值模块，公开调用保持。

Image.hypot 按配对波段实际计算稳定比例范数，保留 NoData、广播／命名、左属性和来源；显式 Float32 输出，Float64 callback 输入仍拒绝，500 图节点上限不变。3e30／4e30 与 3e-30／4e-30 避免中间平方问题；动态真实范数超过 Float32 仍可产生 inf，可预知的常量溢出则提前拒绝。SDK 文档和社区教程的 atan2 约定冲突、动态溢出与未运行的 E/G 见 [数值政策](numerical-policies.md)，不能把这些本地结果当作 Google 等价证明。Image.atan2 及其底层 arctan2 进程仍未开放。

示例 20 与 `ee-harmonic-amplitude-v1.json` 复用前批日期／集合数组／矩阵求解链路，实际计算 cosine／sine 系数的振幅。正负 `(3/10,2/5)` 均得到 1/2，零向量为 0，含噪 `(1/5,121/1000)` 为 `sqrt(54641)/1000`；独立 Fraction 正规方程与平方根参考验证，向量算子另有 Decimal 高精度控制；缺测与非矩形景界仍掩膜。振幅／完整系数／截距／目标预测各为 200／215／139／219 节点，网络尝试 0；S/C/静态及采样点 N 通过，无实际 E/G，也没有伪造栅格相位。

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
| `regression_reducer` | passed | rejected | ImageCollection.reduce linearRegression requires exactly 3 scalar bands per frame；原探针实际使用 5 bands，属于输入数量不匹配 |
| `classifier_constructor` | passed | rejected | Unsupported Earth Engine algorithm: Classifier.smileRandomForest |
| `export_image_drive` | passed | passed | NIR |
| `export_table_drive` | passed | passed | {"features":[{"geometry":{"coordinates":[[[100.1,30.1],[100.9,30.1],[100.9,30.9],[100.1,30.9],[100.1,30.1]]],"type":"Polygon"},"properties":{"mean":3,"scene"... |

## 第十六批：轴拼接、整块重复与双响应数组求解

Image.arrayCat 必须提供 image1／image2／axis，只接受 rank 1..8 的单个固定数组，非拼接轴长度相同。输出保留真实行主序单元和 dtype，合取两个输入的整体掩膜，沿用左名称／属性和既有来源回退政策；不做标量广播或多数组波段配对。

Image.arrayRepeat 必须提供 input／axis／copies。固定签名中 copies 是 Image，Python wrapper 的 Any 注解不改变该签名。本地子集要求其为单标量波段的有效纯常量正整数，真实执行常量表达式及每层 Float32／Double 转换；有源、映射、footprint、掩膜、动态值、零／负值及非整数均拒绝。重复整个轴块，例如 `[1,2]` 重复两次得到 `[1,2,1,2]`。两项操作均限定已有非负轴，保留 rank≤8、每轴／总单元≤64、共享 50000 工作步和 500 图节点预算，输出构造前收费。这些限制是本地支持子集，不是 Google 服务的完整参数限制。

`examples/21_GEE_python_multi_response_arrays.py` 与 `tests/fixtures/ee-multi-response-arrays-v1.json` 将四景按实际时间排序，用 arrayRepeat 构造截距列、arrayCat 拼入自变量及两个独立响应列，再经显式 Float32 matrixSolve 求解。设计矩阵为 `[[1,0],[1,1],[1,2],[1,3]]`，正规矩阵为 `[[4,6],[6,14]]`。第一样点两响应截距／斜率分别为 `(2,3)` 和 `(-1,1/2)`；含噪声样点为 `(1,2)` 和 `(-2,1/2)`，两响应残差分别为 `[1,-1,-1,1]` 与 `[2,-2,-2,2]`。

系数、拟合、残差独立编译为 208／284／328 节点，Fraction 闭式和独立 NumPy SVD 按 2e-6 容差核对。任一响应任一帧缺失会掩膜两个响应的全部结果，不进行完整行删除；保留实际帧顺序、负／零值和 bbox 内但非矩形场景外的掩膜控制。SDK 网络入口尝试为 0。S/C/采样点 N 与未运行的栅格 E／Google G 分开登记，见 [第十六批报告](../../reports/gee-python-wave16.json)。

## 复现与后续顺序

```sh
.venv/bin/python -m scripts.ee_python_inventory
.venv/bin/python -m scripts.ee_python_probes --check
.venv/bin/python -m pytest -q
npm --prefix web test
.venv/bin/python scripts/build_web.py
```

继续按真实 Python 项目依赖补全栅格数组、逐像元回归，然后采样／分类训练预测、矢量／空间 Join、邻域／高级时序；优先使用版本化合成样本验证计算语义，本阶段不推进 Linux 隔离适配或要求原生／真实数据验收。当前剩余的 5 项定向拒绝是全局 footprint unmask、Kernel.square／邻域、focalMean、原回归探针的输入数量错误和 smileRandomForest；它们只是已探测缺口，不是剩余功能的完整清单。

[GOAL.md](../../GOAL.md) 记录持续目标；[云端交接](../cloud-handoff.md) 保留环境和发布约束。Python 达标后再系统推进 JS，期间共享后端改动持续回归已有 JS 功能。
