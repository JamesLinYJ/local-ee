# GEE Python／JavaScript 兼容范围

第三十六批新增 **14个有限静态入口**：UTC日历4、Array选择3、内联表3、Number.expression1、String正则3，并扩展已有Dictionary.select/remove的RE2正则选择。完整回归 **3644 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十三项结果一致，两行CSV通过合成dispatch／worker／结果读回。名称 **491／991（49.55%）** 仅为入口统计，不代表完整语义兼容。固定RE2依赖的OSV／PyPI已知告警查询为0，原锁定包版本未变；50000工作预算保持。未启动或部署业务服务，Google／真实数据／生产验收仍未完成。见 [语法清单](gee-python/list.md)、[示例41](../examples/41_GEE_python_metadata_tables.py) 和 [报告](../reports/gee-python-wave36.json)。

第三十五批新增 **61个有限静态入口**：Number类型转换24、Array类型转换26、特殊函数8、容器筛选3，包含25个单列别名。最终完整回归 **3409 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十一项输出一致，三行CSV通过合成dispatch／worker／结果读回集成。名称 **477／991（48.13%）** 仅为入口统计。原预算保持，未改依赖或重建JVM，未启动业务服务；没有新增栅格／浏览器／生产／Google验收。整数舍入推断、Int64精确域和正则等限制单列，整体目标仍进行中。见 [语法清单](gee-python/list.md)、[示例40](../examples/40_GEE_python_numeric_preparation.py) 和 [报告](../reports/gee-python-wave35.json)。

第三十四批并行新增 **39个入口**，含16个实际Image科学函数、Array位运算／向量／padding及Number解析／别名。冻结便携 **3180 passed／10 skipped**（另排除4项延期原生测试），七个可信JVM／GeoTrellis组件、前端11／类型／构建通过；Python／JS十项组合输出一致。名称入口 **416／991（41.98%）**，其中本批12个为官方单列别名，不是完整参数／语义／Google兼容率。修复常量数学逐景绑定、不同atan2来源隐式重采样和4000景普通map的新增预算开销，原预算不提高。Float32精度和极点政策明确；未部署，无完整Spark／服务／浏览器／Google验收。见 [影像数学语法](gee-python/pixel-math.md)、[示例39](../examples/39_GEE_python_pixel_math.py)、[报告](../reports/gee-python-wave34.json)。

第三十批补齐已有Classifier.train的元数据默认字段，以及内联集合的Element元数据和行操作传递。冻结源码 **2640通过／3跳过**（另排除4项延期原生测试），六个可信JVM／栅格组件与前端11／构建通过；自动字段规格由官方客户端编译后进入实际Smile训练／预测，另有独立MD数值和Python／JS图对照。入口仍 **278／991（28.05%）**，不是完整兼容率。sampleRegions v1默认字段、动态取样元数据修改及全量API仍有缺口；完整Spark／服务／浏览器／部署／Google未验收。见 [语法](gee-python/training-schema.md)、[报告](../reports/gee-python-wave30.json)。

第二十九批新增有限 `FeatureCollection.randomColumn`，完整保留采样后新增／覆盖列的schema与结果，接通训练／验证随机划分及真实RF链路。冻结源码完整回归 **2600通过／3跳过**（另排除4项延期原生测试），六个可信JVM／栅格组件和前端11／构建通过。入口 **278／991（28.05%）** 仅为名称；原50探针45编译／5拒绝。32行真实组件样本分为16／16并进入实际Smile训练与预测，矩阵频数通过；本地随机序列不承诺Google相同，无完整Spark／批任务／浏览器／部署／Google验收。见 [语法](gee-python/random-split.md) 和 [报告](../reports/gee-python-wave29.json)。

第二十八批新增实际 `Image.sample` 的有限 ROI／footprint、比例／近似数量抽样、null、中心几何及元数据，兼容既有显式 schema 分类和样本任务路径。入口 **277／991（27.95%）** 为 API 名称统计，不能当作完整兼容率；原50探针仍45编译／5拒绝。冻结源码回归2493通过／3跳过，五个可信 JVM 组件与前端11／构建通过。完整 Spark／部署／浏览器／Google 同数据未验收；本地随机算法不承诺 Google 抽中行一致。见 [语法](gee-python/image-sampling.md) 和 [报告](../reports/gee-python-wave28.json)。

第二十七批扩展已有 API 的真实运行链路：RF 要素分类 → 训练重代入／独立验证矩阵 → 七种指标访问器 → 受控 JSON getInfo 或分类表 CSV 导出。相同取样表复用固定训练分支，空表／缺值／重名／未定义指标与图类型边界有回归。便携 Python **2413 passed／3 skipped**（另排除4项延期原生测试），前端 **11 passed**／类型检查／构建通过；实际 JVM 要素预测／重代入计数及四个真实栅格组件已验。入口仍为 **276／991（27.85%）**；这不是参数或完整计算兼容率。详见 [验证语法](gee-python/rf-validation.md) 和 [报告](../reports/gee-python-wave27.json)。本批未部署，完整 Spark／服务／浏览器／Google 同数据未验收。

基线：官方 `@google/earthengine` 1.7.49，仓库提交 `e189e4b89e785019ea5642ea8e80cb644749cd4a`。客户端构造和序列化逻辑直接复用官方构建；签名文件也固定到同一提交，见 `vendor/earthengine-js/upstream-lock.json`。

Python 编辑器同时提供官方 `earthengine-api` 客户端入口，版本 1.7.49 固定在同一上游提交的 Python 子目录；许可证、源码树及关键文件摘要见 [`vendor/earthengine-python/upstream-lock.json`](../vendor/earthengine-python/upstream-lock.json)。Python 和 JavaScript 会生成相同格式的 EE 表达式并进入同一个本地兼容层；二者都不连接 Google 计算服务。客户端语言和官方 SDK 覆盖面不表示本地编译器已支持所有调用。

第二十六批增加有限真实 `Classifier.smileRandomForest`：内联／采样表只在可信 JVM 训练，六参数保留，opaque 模型只接影像预测；实际 Smile1.5.3、独立依赖锁与本地 SPI，未安装到当前运行环境。完整便携回归 **2293 passed／3 skipped**（另排除4项延期原生测试），前端11／构建通过，新增3项Python／JS官方SDK图一致性，四个实际tile组件通过。1000行×8特征×100树规模训练与256×256 tile预测已验，最终Unicode原生复核单列；这些不是完整Spark／服务／浏览器／Google验收。入口 **276／991（27.85%）** 仅为名字；RF explain／表分类／验证矩阵／随机列／其他模式／band_order自动schema仍有缺口。见 [RF语法](gee-python/random-forest.md) 与 [报告](../reports/gee-python-wave26.json)。

第二十五批新增有限 `Image.remap`、`Filter.expression` 和取样后 filter／无排序 limit，贯通标签准备、样本筛选及真实样本训练的编译和运行时桥。便携 Python **2068 passed／3 skipped**（另排除 4 项原生测试）、前端 **11 passed**／构建通过，77 项 Python／JS SDK 一致性；三个真实 tile 内核通过。入口清单 **275／991（27.75%）** 仅是 handler 名称统计，部分参数仍受限；完整 Spark／部署／浏览器／真实数据／Google 同数据均未在本批验收。见 [语法文档](gee-python/sampling.md) 和 [报告](../reports/gee-python-wave25.json)。该批尚未实现随机森林。

第二十四批补齐有限 `Image.sampleRegions → minimumDistance.train → Image.classify` 编译与运行时桥、样本 getInfo／CSV 任务合同。参数和网格政策见 [取样语法文档](gee-python/sampling.md)，证据见 [报告](../reports/gee-python-wave24.json)。当前便携 Python **1882 passed／3 skipped**（另排除 4 项原生测试），前端 **11 passed**／TypeScript／构建通过；实际取样／分类 tile 内核已验，完整 Spark、部署、浏览器、真实数据和 Google 对照仍未运行。当前声明入口 **273／991（27.55%）**，只统计 API 名称，部分参数仍受限，不能作为完整语法或计算语义兼容率。

## 执行链路

JavaScript 在 macOS 原生 Seatbelt 隔离的 Node.js 进程执行；Python 脚本在独立的 Python Seatbelt 进程执行。相应官方 SDK 构造 EE 表达式，兼容模块将支持的表达式编译为 openEO 流程图，沿用已有队列、数据快照和禁止公网访问的原生 GeoTrellis 任务。Python EE 运行器仍提供原有 openEO `connection`；可选择 `import ee` 使用本地初始化的官方客户端。兼容模块没有另建计算集群或公网服务，当前部署不使用虚拟机或容器。

Python 运行器会将 `ee.Initialize()` 绑定到本地脚本令牌和 `/gee/v1/dispatch`，禁止认证提示、Google OAuth、项目发现及公网回退。Python `Map` 是工作台提供的本地图层/视图适配器。`ee.batch.Export.*.toDrive` 在支持范围内映射为本地任务和文件；名称沿用官方 SDK，不会上传 Google Drive。此入口共享下方 API 清单和参数限制，不会因为 SDK 接受某个方法调用就将其视为已实现。

本轮原生验收覆盖 getInfo、地图、官方 Task 启动／状态／取消／列表、GeoTIFF 与区域 CSV 下载，以及并发重试去重；Edge 中的 Python 示例也已运行并显示结果。Python 图像导出当前仅支持 GeoTIFF，地图 ID 是本地异步任务引用，不提供 Google tile_fetcher。范围与证据见 [Python 客户端报告](../reports/gee-python-client.json)。

官方仓库是客户端绑定。`imagecollection.js`、`collection.js`、`filter.js`、`customfunction.js` 和 `serializer.js` 是语法适配依据；官方客户端出现某个方法不代表本地具有其服务端算法。例如 `Filter.inList` 的官方实现交换参数后调用 `Filter.listContains`，本地需要接收实际生成的图。

## 支持清单与验证层次

S 表示固定官方 SDK 可生成表达式；C 表示本地编译；E 表示实际引擎执行；N 表示独立数值基准；G 表示与原始 Google 服务同数据比较。历史栅格 N 证据包含实际引擎执行，新静态值 N 只验证本地静态算法，不表示 GeoTrellis 栅格验收。下表所有项目尚无 G 级结论。`/gee/v1/capabilities` 的函数名是 C 级处理器清单，不是 991 项服务端算法均已实现。

完整固定签名、参数与验证层次见 [全量 API 清单](gee-api-inventory.md) 和 [机器可读报告](../reports/gee-api-inventory.json)。该清单可以在没有本机数据和审计目录的干净克隆中重新生成；不会用声明数量推算兼容率。

Python 优先的全量类型／方法／参数绑定记录另见 [Python 清单](gee-python/list.md) 和 [Python API 报告](../reports/gee-python-api-inventory.json)。2026-10-22 的便携增量修复 Python 命名 GeoJSON CRS 解码，补充 `Filter.notNull`、Dictionary／List.sequence、有限元数据 Join 和静态 Array／矩阵算法。第四批新增有限数组算术／布局／归约、对称特征分解及 Cholesky，闭式 PCA 验证中心化至重建；完整参数限制和本地数值政策见 [第四批报告](../reports/gee-python-wave4.json)。这些静态证据不覆盖栅格 `Image.array*` 或 Google 对照。SDK 初始化也不再获取 Google 弃用资产目录；探针实际拦截并计数 Python 网络入口，不将该计数描述为内核抓包或用户代码沙箱。

第二批增加有界内联 FeatureCollection、表格 linearFit／linearRegression、数值时间差度量 Join、Number.format 和 String 的构造／工作预算。静态合成表格工作流有独立手算数值参考；本轮原生引擎与 Google 同数据对照未运行，见 [分层验证报告](../reports/gee-python-wave2.json)。

第五批增加固定形状单数组波段的 Image.toArray、布局／长度、单输出归约及矩阵乘法，同形算术与静态数组常量可衔接。类型化数组只作为计算中间值，flatten/get 后进入既有像素后端；静态 PCA 基应用到本地波段的投影与重建有独立合成图 N，整体掩膜与来源均保留。总 64 单元、8 轴、每轴 64 及既有图／工作预算适用；动态形状、多数组波段、广播、掩膜坐标和数组直接导出仍拒绝。详见 [第五批报告](../reports/gee-python-wave5.json)，实际栅格引擎与 Google 对照未运行。

第六批将 linearFit 扩展到有限 ImageCollection：每像元删除 x/y 不完整行，两遍中心化 OLS 输出 scale／offset，同日多景和显式重复观测分别计入。版本化时间趋势示例与独立 SVD 校核覆盖拟合、空间掩膜、退化和目标日期预测。限 1..8 帧、两个同名同序标量波段、binary NoData 和 parallelScale=1；保留 Float32 callback 与图／工作预算，完整多变量回归、权重及类型提升仍待实现。证据见 [第六批报告](../reports/gee-python-wave6.json)，无实际栅格 E/G。

第七批新增有界静态 ConfusionMatrix 的构造、array／order／accuracy／kappa，以及内联 FeatureCollection.errorMatrix。版本化分类标签评估先显式筛除缺失，再按类别表计数，以独立频数核对总体准确率和 Kappa。仅有 S/C/静态 N，不含采样或分类器训练／预测；完整限制和证据见 [第七批报告](../reports/gee-python-wave7.json)。

第八批增加七项有限 List 布局算法和 List.reduce，实际支持单输出归约及多输入无权回归。示例从列列表组装二次设计矩阵、拟合两个响应并预测，闭式系数、RMS 与残差正交性提供独立 N。zip/unzip 的正常截短行为与科学工作流的等长校验分别验证；空值政策、预算及未支持范围见 [第八批报告](../reports/gee-python-wave8.json)，无栅格 E/G。

第九批增加有限静态欧式最小距离模型，真正训练类均值、预测独立要素并计算训练／验证误差矩阵。只支持 kNearest=1、CLASSIFICATION、完整平面数值属性和唯一最近类；精确 binary64 有理数政策及限制见 [第九批报告](../reports/gee-python-wave9.json)。S/C/静态 N 通过，不含图像分类、采样、随机森林或 Google 对照。

第十批新增有限栅格 linearRegression：过原点或字面量单位截距模型、1..4 响应、联合完整行与 n>numX、真实系数／RMS 数组。多数组波段须选择后标量化；四景双响应例分别输出各响应以满足现有 500 节点上限。参数、图规模和独立 SVD／掩膜证据见 [第十批报告](../reports/gee-python-wave10.json)，不代表通用多变量系统或实际 E/G。

第十一批只折叠待生成的单波段维度／标签元数据，保留全部数值 callback 和源／掩膜／类型边界。上述六个图缩为 333／394／337 节点各两条，完整四系数和双预测图现为 405／413；双 RMS／八字段组合仍超出 500。独立参考、共享表达式标签及同日／重复观测控制见 [第十一批报告](../reports/gee-python-wave11.json)，无实际 E/G 或吞吐声明。

第十二批增加静态方阵 QR／LU／SVD 分解及真实 typed 因子字典组合，合成三端元光谱解混用独立分数参考核对丰度、噪声影响与重建。LU 零主元／非有限结果、矩形形状和预算外输入明确拒绝；QR／SVD 符号及重复值基为 NumPy/LAPACK 政策。见 [第十二批报告](../reports/gee-python-wave12.json)，不代表 Image.unmix、栅格分解或 Google/EJML 等价。

第十三批新增单数组波段的真实 toFloat 和有限 Image.matrixSolve：静态满列秩设计 A(m,n)、栅格 B(m,k)，双方显式 Float32，m<=8、n/k<=4、m>=n。真实伪逆乘像素保留整体掩膜和现有预算，任意响应缺失会掩膜完整解。合成光谱估计／重建／残差有独立 Fraction 参考，见 [第十三批报告](../reports/gee-python-wave13.json)。NumPy 秩政策和 callback 舍入不等于 Google 数值语义；动态设计、数组 Float64、实际 E/G 仍未验证。

第十四批增加有限 ImageCollection.toArrayPerBand、静态 Image.arrayReshape 和 Number.sin／cos，把日期元数据驱动的七景谐波设计接入栅格 matrixSolve。各波段独立保留全帧掩膜，同日不同景保持顺序／身份，Fraction 和独立 SVD 核对系数、正交残差和未来日期预测。参数与证据见 [第十四批报告](../reports/gee-python-wave14.json)；dropMasked=true 的变长模式、动态形状、完整谐波分析及实际 E/G 不在此子集中。

第十五批增加静态 Number／Array 的 hypot／atan2，以及由既有像素算子实现的 Image.hypot，实际衔接谐波振幅；独立 Decimal／Fraction 参考验证稳定范数、轴约定和缺测。动态 Float32 范数超范围可能为 inf，已知常量溢出预检拒绝。SDK 与社区教程的 atan2 约定有冲突，Image.atan2 的 JVM 支持证据不足，均在 [数值政策](gee-python/numerical-policies.md) 和 [第十五批报告](../reports/gee-python-wave15.json) 明确记录；无 E/G 结论。

第十六批增加单数组波段的 Image.arrayCat／arrayRepeat：沿现有轴拼接真实行主序单元，或按可证明有效的正整数常量 Image 次数重复完整轴块。拼接合并整体掩膜，重复保留输入掩膜与 dtype；动态／带掩膜／有空间限定的次数、空轴和多数组波段拒绝。与固定设计的 matrixSolve 串联双独立响应工作流，参数及 S/C/N 证据见 [第十六批报告](../reports/gee-python-wave16.json)；原有 64 单元、50000 工作步及 500 图节点限制保留，无实际 E/G 结论。

第十七批增加固定单数组的 Image.matrixDiagonal／matrixToDiag／matrixTrace／matrixDeterminant，实际提取对角列、插入零值或计算逐步 Float32 和／积。四景双波段中心化、转置乘法和无偏样本协方差串联这些描述量，独立 Fraction／NumPy 参考验证正负协方差、奇异矩阵、整体缺测及场景边界。参数子集和非稳定多项式行列式政策见 [第十七批报告](../reports/gee-python-wave17.json)；没有新增后端进程或移除图／工作预算，无实际 E/G 结论。

第十八批增加固定 Float32 数组的 Image.arrayAccum（默认 sum，以及 min／max）和缩放 Image.matrixFnorm，修复单数组 Image.select 的合法名称／下标选择及改名。跨年同日双景的累计 NDVI 异常使用真实前缀表达式及范数，Fraction／Decimal／NumPy 参考验证顺序、负／零值、完整数组掩膜、大小数值与预算边界，见 [第十八批报告](../reports/gee-python-wave18.json)。其他 reducer、动态形状、通用 Float64 和 Google 数值等价仍未覆盖。

第十九批增加 Array.argmax 与 Image.arrayArgmax：真实按行主序求首个最大值的每轴坐标，静态 typed 空切片返回 null、rank0 返回 []；栅格限显式 Float32 固定单数组，保留包括非赢家缺测在内的完整掩膜。合成 red／nir 光谱用三个明确原型的真实平方距离选择索引，独立 Fraction／Decimal／NumPy 验证并列、零、负分数和空间边界。栅格坐标以整数值 Float32 表示，未宣称 Google Integer dtype 等价，也未实现 Image.classify，见 [第十九批报告](../reports/gee-python-wave19.json) 与 [数值政策](gee-python/numerical-policies.md)。

第三批增加 `Join.inner`、唯一 maxDifference 的 And 组合，以及匹配 Feature 映射回 ImageCollection 的链路；最近前后观测插值有版本化合成来源／掩膜／目标时间参考，见 [第三批报告](../reports/gee-python-wave3.json)。S/C 与合成图 N 通过仍不构成原生引擎 E 或 Google G。

| 用法 | 当前支持范围 | 证据 |
| --- | --- | --- |
| 普通 JavaScript | var/let/const、函数/箭头函数、对象、数组、循环；由 Node 执行 | 隔离运行器与网页实测 |
| ImageCollection / Image | 已入库 Sentinel-2、first、select、rename、map、filter、sort、limit、size | S/C；真实单景 N |
| 日期筛选 | filterDate 毫秒级 `[start,end)`，单参数为 1 毫秒；filterBounds 只选择影像 | 官方 SDK 夹具、边界测试；空间 clip 有真实样本 N |
| 属性筛选 | equals/lt/gt 及逻辑组合、inList/listContains、calendarRange、stringContains | S/C；属性来自本地元数据，缺失字段报错 |
| 集合属性 | aggregate_array、toList(count,offset)、get/date、set/copyProperties | S/C；toList 最多 1000 景 |
| 波段运算 | 四则、比较、逻辑、常用数学函数、addBands 重名/覆盖、expression | S/C；NDVI、条件运算 N |
| 归一化差值 | normalizedDifference 保留负输入掩膜、默认 nd 名称、属性清除规则 | 真实数据与含负值夹具 N；本地零分母掩膜策略尚无 G 对照 |
| 掩膜与条件 | 二值 updateMask、mask getter、where、clip | N；where 条件或替代值缺测时保留原值，原图缺测不复活 |
| 范围变换 | clamp、unitScale；后者不截断范围外数值 | S/C/N；要求有限 low < high |
| 归约 | median/mean/min/max/sum/count、已实现单输出 Reducer、Image.reduce | S/C；多景 median/mean/sum/count、波段 mean 已有 N |
| mosaic | 按集合顺序从后向前取有效像素，反序与相同时间戳仍保留逐景身份 | 正/反序 N；相同时间戳 C 回归 |
| qualityMosaic | 按质量波段最大值选择整组像素，获胜景某波段缺测则保持缺测；排除质量缺测景；当前要求波段名称/顺序一致 | 正序、反序与显式集合 6 个实际输出 N；平分采用本地后景优先规则，未做 G 对照 |
| reduce / toBands | Collection.reduce 输出波段带 reducer 后缀；toBands 按 system:index 命名 | S/C/N；toBands 最多 100 波段，仍受 500 图节点限制 |
| fromImages / merge | 从显式列表、toList、List.map 的分期影像构造集合；保留重复项；逐景 map 属性、筛选、排序、归约、toBands | S/C/N；分期合成跳过空段、重复求和/计数与排序 mosaic 已有实际引擎验收；有限集合最多 1000 幅 |
| Date | UTC 构造/fromYMD/get/millis；advance 秒至周、整数月/年；常用 format token；difference/getRelative/getFraction | S/C；毫秒、月末、闰年、负向移动、格式错误；平均年月与日历 fraction/ISO 周边界采用显式本地策略并警告，没有 G 对照 |
| 逐景元数据 map | 原始集合读取 date/get/propertyNames/geometry 时自动有限展开；支持 set/copyProperties、dropNulls，保留同日不同 item 和排序 | S/C；逐景日期参与像素计算另有实际引擎 N；纯像素 map 保留紧凑路径 |
| 浮点类型转换与归约 | toDouble/toFloat 转换物理像元类型；Float64 有界逐景／波段 mean、median、min、max、sum、count、first、last、sampleStdDev | 独立 SPI 与 GeoTIFF N；保留毫秒日期、同时间戳场景和二值 NoData。通用像素回调仍需显式 toFloat，未承诺完整类型传播 |
| 常量与日期波段 | addBands 接受有限常量、静态算术及逐景 date().millis()，按目的影像的有限本地网格和 footprint 求值，常量有效性不继承源波段缺测 | S/C/N：14 用例、18 输出波段与独立基准均为 0 掩膜差异、0 数值误差，包括全缺测源、不同 footprint、同时间戳场景、均值／计数／样本标准差／toBands。见 reports/gee-constant-wave5.json；未做 G 对照 |
| 缺测填充 | unmask 默认有效 0、标量、单波段广播和等波段数按顺序替换；保留输入属性、替代值掩膜与默认 footprint；map 自动按场景 footprint 展开 | S/C/N：5 项 SDK→原生输出及不同足迹、相同时间戳的逐景均值验收均为 0 掩膜差异、0 数值误差；SPI 另验缺 tile 与拒绝控制。仅有限、对齐的本地网格与相同观测时刻；global constant + sameFootprint=false 拒绝。结果为 Float64，通用后续算术需显式 toFloat，未完成 Google 对照 |
| Number 位运算 | 标量 bitCount/bitwiseNot/bitwiseAnd/Or/Xor/leftShift/rightShift 的受限整数域 | 官方 SDK 与文档样例 C；signed64 整数输入，And/Or/Xor 限非负，左移限非负且不溢出，移位量 0..63；非整数、超范围明确拒绝；不是 Image QA 位运算 |
| List／Dictionary | sequence 支持 count/end 与 count/step；get/length/contains/add/cat/slice/distinct/sort/map/iterate；Dictionary get/keys/values/contains/set | S/C；序列另有 NumPy/Python 独立参考，空 keys 保持空列表，缺键必须有非 null 默认值；回调最多 1000 项，中间列表最多 10000 项，结果最多 1 MB |
| 非空属性筛选 | Filter.notNull；多属性全部非 null；缺失/null 拒绝，0/False/空字符串等非 null 值保留 | S/C；空属性列表匹配全部，最多 1000 属性并计入编译预算；本地平面属性名，无 G 对照 |
| 有限元数据 Join | simple/inverted/saveFirst/saveAll/saveBest/inner/apply；元数据比较、排序、outer、唯一直接或 And 中的 maxDifference 度量，匹配后读取／组合真实来源影像 | S/C；独立绝对差、最近前／后观测、源身份及掩膜合成图参考；最多 1000 景／inner 匹配对、共享 50000 步；请求度量时 Or/Not 中的度量或多度量拒绝；无矢量／空间或原生 E/G |
| 有限表格回归 | 内联 FeatureCollection.reduceColumns，linearFit／linearRegression、类型化系数矩阵和各响应残差 RMS；缺失/null 行跳过 | S/C 与闭式独立 N；最多 1000 行／32 输入列，非空权重拒绝；秩不足和 n<=numX 返回 null；不含影像／栅格回归或 G |
| 静态字符串和格式 | String 数值构造、cat／length／compareTo；Number.format 的有限 %s／%d／%f | S/C；拼接分配前和共享工作预算；Python Unicode code point／数值拼写及十进制半入政策均无 G；高级转换／格式拒绝 |
| 静态 Array／矩阵 | 构造、get/length/toList/reshape/transpose、matrixTranspose/Multiply/Inverse/PseudoInverse/Solve | S/C 与静态独立 N；整数精确域不超过 2^53、最多 8 轴／10000 单元及共享工作预算；线性求解只接受满列秩方阵／超定矩阵；不含 Image.array*、栅格回归或分类器 |
| 有限分类评估 | 静态 ConfusionMatrix、array／order／accuracy／kappa、有限 consumersAccuracy／producersAccuracy／fscore；内联 Collection.errorMatrix | S/C 与独立标签频数 N；<=64 类／4096 单元、非负整数计数总和 <=2^53、<=1000 完整记录，共享预算；缺失／null、未定义分母、原始 List／浮点计数 Array、直接对象 JSON、Feature 属性对象拒绝；逐类 rank1 Float64／Fβ 轴为本地政策，无 E/G |
| 有限 List 计算 | zip／unzip／flatten／repeat／reverse／set／swap，List.reduce 的单输出归约及 linearFit／linearRegression | S/C/独立静态 N；布局 <=10000 顶层值、flatten 深度 96、reduce <=1000 行／32 回归列，共享工作与公开物化预算；typed Array 保留；空值／低样本政策明确且无 G 对照，不含任意 reducer 组合／权重 |
| 最小距离分类 | minimumDistance／train／schema／CLASSIFICATION 模式、FeatureCollection.classify、训练 confusionMatrix、有限 Image.classify | S/C/独立静态与合成图 N，另有真实 JVM tile 内核组件 N；欧式／曼哈顿／光谱角、k=1、1..1000 训练行／1..8 平面属性、类别 0..63、无子采样、共享预算；影像按 schema 取波段，保留精确模型及输入精度，输出 Int32 NoData；完整 Spark／运行器／Google、采样及其他分类器未验收 |
| 静态方阵分解 | QR 的 Q／R，部分选主元 LU 的 L／U／P，SVD 的 U／对角 S／V；typed 因子可继续矩阵计算 | S/C/闭式与分解恒等式 N；所有因子 n×n，合并输出 <=10000 cells、共享立方工作预充；LU 计算零主元和非有限消元拒绝，QR／SVD 符号／退化基未作 Google/EJML 对照；无矩形／栅格 E/G |
| 有限栅格 linearRegression | numX=1 过原点，或 numX=2 且首列为可证明单位截距；numY=1..4，系数／RMS 命名数组波段 | S/C/独立样点 N；1..8 同序帧、所有输入共同完整行、n>numX／非退化、RMS 按 n；parallelScale=1、Float32 callback 和现有工作／图预算；多响应按需单独物化，无通用设计矩阵／E/G |
| Algorithms.If | 静态条件，惰性编译选中分支 | S/C；不把影像对象当作静态布尔条件 |
| 几何与地图 | 平面 WGS84 Geometry；Image/Collection/Feature.geometry；Map.centerObject、setCenter、addLayer | S/C；真实地图和 RGB 预览 N |
| 影像导出 | toDrive 适配本地 GeoTIFF/NetCDF；region 精确掩膜、scale/crs、fileNamePrefix | 真实三角形区域 N；网页文件名回读 |
| 区域统计与表格 | reduceRegion、区域 CSV、有限内联 FeatureCollection／分类要素 CSV，selectors 选择和排序 | 区域单景均值 N；内联表格为真实 CSV 合成路径，≤1000 行／256 列／50000 单元及输入输出预算；本地序列化政策与真实部署验收分别记录 |
| maxPixels | 正有限整数；允许常见 `1e13` 上限，但保守像素预检与本地 1 亿像素/波段上限同时生效 | 正/负测试与实际导出；不提高 CPU/内存/时间预算 |

## 网格、逐景与开销

当前上游 STAC 加载路径将观测归到 UTC 日。兼容模块对集合归约分别加载选定 item，得到逐景影像后在明确的轴上归约，避免把同一天的不同观测先合并。原始 STAC 日期和科研数据保持不变，没有虚构时间戳。整个流程仍在一个批处理任务中执行。

这一策略优先保证正确性，代价是图随景数和波段数增长。当前保留每图 500 节点限制，过大的流程明确拒绝；不把它描述为适用于无限时间序列的性能方案。编译器只加载实际使用的源波段，并缓存相同节点。后续可在独立适配器中实现保留精确观测轴的高效加载路径，再替换这段编译策略。

GEE `where` 和 `updateMask` 的含义与底层算子不能直接混用。实际多景测试还发现 JVM 归约器可能复用输入 tile；兼容回调为复用的归约参数提供副本，避免条件分支中的计数修改后续求和输入。

## 迁移示例

```js
var roi = ee.Geometry.Rectangle([113.55,22.30,113.57,22.32]);
var scenes = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(roi).filterDate('2024-01-19','2024-01-20');
print(scenes.aggregate_array('system:index'));
var dates = ee.List.sequence(0,2).map(function(m) {
  return ee.Date.fromYMD(2024,1,31).advance(m,'month').format('yyyy-MM-dd');
});
print(dates);
var ndvi = scenes.map(function(image) {
  return image.normalizedDifference(['B8','B4']).rename('NDVI')
    .copyProperties(image,['system:time_start']);
}).median().clip(roi);
Map.centerObject(ndvi,13);
Map.addLayer(ndvi,{min:0,max:1,palette:['f4e5b9','155b3b']},'NDVI');
Export.image.toDrive({image:ndvi,description:'NDVI',fileNamePrefix:'ndvi',
  region:roi,scale:10,crs:'EPSG:32649',maxPixels:1e13});
```

完整可运行例子位于 `examples/javascript/04_日期列表与条件运算.js`，网页脚本资源中直接选择。导出任务创建后点击“开始导出”，或对返回任务调用 `start()`。

逐景日期、NDVI 质量合成和末端 Float64 导出见 `examples/javascript/06_逐景日期与质量合成.js`。`toDouble()` 不会补回先前 Float32 计算已经损失的精度；有界逐景归约使用独立 Float64 适配器，通用像素回调尚不支持 Float64。

`examples/javascript/07_缺测填充与掩膜.js` 演示 `unmask`、clip 保留和 Float64 导出。标量填充值不是恢复观测；跨网格或跨时间替换仍需明确对齐。原生扩展单独构建为带源码/依赖摘要的 SPI JAR，构建入口保持 `scripts/build_integer_adapter.py`；整数转换、有限网格常量、缺测替换和 Float64 归约分开组织，不修改上游 JAR。

常量与逐景日期 band 的模板保留维度操作，单景时间轴可先降为空间网格后生成常量，因此全缺测源仍可产生独立有效常量。纯空时间栅格不会被擅自补出观测时间。求值网格不改变常量逻辑上的默认 WGS84／1 度投影；该投影的查询与逐波段重投影仍明确拒绝。

## 尚未支持

- 全球 GEE 数据目录、私有 assets、任意 `require('users/...')` 模块和 Google Drive/Cloud Storage 上传。
- 独立纯常量栅格与纯常量集合缺少明确的本地网格，仍拒绝；绑定到本地影像的 addBands 常量与日期 band 已支持。常量投影查询、任意异构类型、逐波段投影与跨网格语义仍需独立实现和验证。
- 除上述静态最小距离子集外的分类器、图像分类、采样、通用设计矩阵的栅格回归、动态形状及其余多数组波段／Image.array* 运算、超出上述有限元数据范围的 join、邻域卷积、ui.Chart/ui.Panel 等完整 GEE 应用组件。已补固定形状数组布局／矩阵投影／归约及有限逐像元 linearFit／linearRegression，不能据此宣称完整栅格回归支持。
- 分数掩膜、球面/测地线几何、非 UTC 时区、分数月/年、任意 Joda 格式 token。
- 任意 CRS transform、导出分片、bestEffort 和自定义 tileScale；不支持的参数明确失败。
- 整数像元类型转换、Image 位运算和原始 GEE 的边界像元加权。GeoTrellis 整型 NoData 哨兵会占用合法数值，不能简单替换 cast 名称；完整类型提升仍待实现。当前 N 验收以浮点数值、网格和二值 NoData 为准。
- 新日期字段只支持 UTC；getRelative 的相同单位、week/month 组合，以及 getRelative/getFraction 的亚毫秒输入明确拒绝。difference 年/月按 365.2425 天/年及十二分之一月计算；getFraction 年/月按实际 UTC 日历长度计算，周按 ISO 周，都会对未完成 Google 对照的策略发出警告。

本地 Sentinel-2 已预去云，仅有 B2/B3/B4/B8/SCL 对应波段；DN 视图是已标准化反射率 ×10000。缺失 QA60/B11 不会被伪造；别名不会恢复已经掩膜的数据。

## 复杂公开工作流抽查（2026-10-21）

读取了官方文档中的谐波回归、矩阵 OLS、随机森林、HISTARFM 插值、s2cloudless，以及作者仓库 LT-GEE 的源码；另选官方 qualityMosaic 教程作为普通用法检查。完整来源及内容摘要见 `audit/gee-complex-compat-v1/sources.json`，工作流缺口见 `findings.json`。

50 个定向表达式均由固定官方 SDK 成功序列化。本地编译中 3 个阳性对照通过，43 个因操作或语义未实现而拒绝，4 个因数据集或波段不可用而拒绝。这是针对所选工作流的缺口检查，不能换算为整个 GEE 的兼容百分比，也不是原脚本全流程或 Google 服务数值对照。

| 工作流 | 已确认的主要阻塞 |
| --- | --- |
| 最绿像素合成 | 历史抽查时缺失；本轮已实现有限同构集合 `qualityMosaic` 并完成 6 个实际输出的独立像素对照；平分规则仍未与 Google 比较 |
| s2cloudless 云影 | 有限本地影像 `Join.saveFirst` 已补；仍缺定向距离变换、`projection/reproject`、`focalMin/focalMax`；云概率数据未入库 |
| 谐波时序与矩阵回归 | 已补有限日期、数组布局／矩阵投影／归约、静态设计的 Image.matrixSolve、逐像元 linearFit／受限 linearRegression，以及定长日期驱动谐波拟合和 Image.hypot 振幅；静态 Number／Array.atan2 按 SDK 轴政策计算；通用动态设计、变长数组和栅格 Image.atan2 相位仍有缺口 |
| HISTARFM 插值 | 已补受限 Date.getRelative、saveAll 匹配影像列表、maxDifference 与方向比较的 And 组合；最近前后观测像素插值有合成图 N，独立常量栅格、int16、完整项目及真实引擎验收仍缺失 |
| 随机森林与验证 | 样本提取、随机森林训练/预测与批量区域统计仍缺；已补有限内联标签误差矩阵、总体及有限逐类指标，不能代替完整分类验证 |
| LandTrendr | GEE 用户模块解析、真实时序分段算法、数组处理、连通像元与 Image QA 位运算仍缺失；已补有限网格的 `unmask`，不能据此运行完整 LandTrendr |
| GEE 应用交互 | 实际原生 runner 的 `ui.Panel/ui.Chart` 返回 `ui is not defined`；`require('users/...')` 返回模块不存在 |

额外 14 个规模编译探针发现：单波段均值 50 景为 302 节点，100 景超过 500；双波段均值 30 景为 335 节点，50 景超过 500。该结果仅测图规模，未测吞吐。需要紧凑而保留精确观测身份的加载/归约路径，不能只放宽节点上限。

数据与算子须分别处理：当前 `Translator.load` 仅放行已验证的 `sentinel-2-l2a`；新增 STAC 数据并不自动获得 Landsat、ERA5 或其他 EE 别名。需要各自的波段、单位、缩放、QA 与实样验收。历史 50 个表达式的计数保持原记录，不作为当前全部实现的统计。

复现探针（无数据库、无任务提交、无网络的原生 Seatbelt）：

```sh
PYTHONPATH=. .venv/bin/python audit/gee-complex-compat-v1/run_probes.py --output /绝对路径/新的审查目录
```

最终有效记录为 `audit/gee-complex-compat-v1/probe-run-v2/validation.json`；v1 的探针初始化错误保留，未作为产品缺陷计数。数组探针使用占位 Image 隔离缺失处理器，不验证数组形状或数值。

## 可重复验证

```sh
node scripts/ee_sdk_fixtures.cjs > /tmp/ee-sdk-fixtures.json
cmp /tmp/ee-sdk-fixtures.json tests/fixtures/ee-sdk-1.7.49.json
.venv/bin/python -m pytest -q
GEE_AUDIT_DIR=/absolute/new/audit-dir .venv/bin/python -m scripts.check_ee_multiscene
```

多景 harness 使用明确标注的合成影像、同日毫秒时间戳和不同波段掩膜，通过原生 Seatbelt 运行固定依赖的引擎，不写入生产目录或数据库。独立 NumPy 基准通过 Rasterio 投影到实际输出网格。保留失败尝试的日志；历史容器验证见 `audit/ee-compat-wave1-r5/validation.json`、`audit/ee-compat-wave2/validation.json`，当前原生 23 项输出见 `audit/native-macos-multiscene-v5/validation.json`。

源码依据：[官方客户端固定版本](https://github.com/google/earthengine-api/tree/e189e4b89e785019ea5642ea8e80cb644749cd4a)、[where 规则](https://developers.google.com/earth-engine/apidocs/ee-image-where)、[unitScale](https://developers.google.com/earth-engine/apidocs/ee-image-unitscale)、[Date.advance](https://developers.google.com/earth-engine/apidocs/ee-date-advance)。


第二十批补静态 Array.sort 和显式 Float32 固定数组 Image.arraySort：按键稳定排序整个切片，保留 NDVI／日期对应关系、完整值与键掩膜及预算；四景质量筛选有独立分数参考。有限逐类 consumersAccuracy／producersAccuracy／fscore 继续准确登记本地返回 rank 与 Fβ 轴推断，未称 Google 完整等价。最终范围、误差及未运行项见 [第二十批报告](../reports/gee-python-wave20.json) 和 [数值政策](gee-python/numerical-policies.md)。

第二十一批扩展静态 minimumDistance 的曼哈顿及 cosine 光谱角分类。三种度量均以真实未归一化类均值预测独立要素，保留 schema、元数据、训练混淆矩阵和逐类指标；固定样本准确率分别为 1/2、5/6、2/3，说明所选度量实际生效。cosine 用带符号精确交叉乘积比较角度，零范数查询／类中心在预测时拒绝，等距继续拒绝。限 k=1／CLASSIFICATION，无 Mahalanobis、采样、Image.classify、栅格 E 或 Google G；详见 [第二十一批报告](../reports/gee-python-wave21.json)。

第二十二批接通内联 FeatureCollection 的 `Export.table.toDrive` 到本地 CSV 批任务，示例 27 串联三种度量的训练、验证、任务启动与真实 CSV 写出。Python 官方 Task 接口和既有 JS 导出 wrapper 均经可信合成控制验证；JS 覆盖对象与位置参数，传输／数据库／队列由测试替身接管，不是实际 HTTP／浏览器／Seatbelt 验收。新分支复用现有权限、结果解析器与受限批任务入口，未部署到运行服务。CSV 默认列、空值、嵌套值和几何规则是明确本地政策，不宣称 Google 文件逐字节相同；其他格式、云端目的地、maxVertices／priority 仍拒绝。范围和剩余项见 [第二十二批报告](../reports/gee-python-wave22.json) 及 [数值与序列化政策](gee-python/numerical-policies.md)。

第二十三批支持已训练 minimumDistance 的有限 `Image.classify`。按 schema 名称选取并排列真实标量输入，额外波段缺测不污染；精确分数模型经严格 wire／图校验进入专用 GeoTrellis 内核，避免通用 Float32 callback 隐式降低精度。单输出保留元数据、来源／有限足迹及时间，Int32 NoData 类别0..63；有效 Infinity、最近类并列和 cosine 零向量按明确本地政策拒绝。示例28覆盖两景、三个类均值（含1/3）、映射、改名、addBands、地图及未启动的导出表达式。真实 JVM tile 内核的141预测／16非法模型／9binary64控制通过，独立合成图参考与完整引擎 E 分开记录。Python1751／3、前端11、构建通过，新增3项官方Python／JS图一致性（共68）。未部署，完整Spark／运行器／浏览器／Google和其余分类器未验收，见[第二十三批报告](../reports/gee-python-wave23.json)。
