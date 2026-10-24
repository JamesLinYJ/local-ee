# GEE Python 兼容清单

## 第六十二批：默认提取与表格边模型

第六十二批修复已有Feature.geometry的官方默认提取、JS的metadata:null属性及CSV任务JSON丢失有效边模型的问题；名称仍709／991（71.54%，仅入口）。完整冻结回归 **6090 passed／27 skipped**，16个源码／样本摘要稳定；双客户端4项成员判断、默认提取与2行真实合成CSV写出／SDK读回通过。独立6.1-sol限定复核81组继承模型及预算／隔离／非法值控制无报告问题，网络尝试0；未做全库安全扫描或Google等价验收。默认area／length／perimeter的6条官方探针仍明确拒绝，已记录WGS84度量与S2固定球模型不能直接等同的缺口。本批没有增加名称、改动原生库或依赖，也未部署服务；完整兼容目标继续。见[报告](../../reports/gee-python-wave62.json)、[提取语法](feature-preparation.md)。

## 第六十一批：有限默认球面路径

省略／空投影的有限Geometry／Feature二元运算已接入固定S2，官方客户端默认写法无需改为平面参数；名称仍709／991（71.54%，只计入口）。完整冻结回归 **6072 passed／27 skipped**、63个摘要稳定，前端11项／类型／临时构建通过。原16条默认表达式全部计算，72次独立非边界点位检查一致；双客户端16方法、9个独立流程探针及4行球面CSV写出读回通过。有效默认值、集合继承、类型合法的公开标志和预算保留；独立原生55项严格期望中52项通过，3项binary64输入／构造结果关联问题仍未解决、未视为用户接受，不能以数值容差通过替代。maxError／一般投影、球面栅格消费者、完整球面公开编码和Google同数据验收仍待完成。未部署服务或修改用户数据；清理约608MB自有临时文件，保留必要依赖与失败证据。见[本批报告](../../reports/gee-python-wave61.json)、[球面合同](spherical-geometry.md)；下方历批数字和限制属于各自历史证据。

第六十批按官方GEE函数／参数补上Geometry与Feature各8个二元运算的有限平面路径，名称693→709／991（71.54%，仅入口；剩282项）。完整回归 **5950 passed／27 skipped**，18个源码／样本摘要稳定；前端11项、类型与临时构建通过。原16个显式EPSG:4326调用由全部拒绝变为全部编译并有限计算；Python／JS的30个输出图一致，10组NDVI共160单元（113有限、47缺测）与独立预期一致；4行要素CSV实际写出读回，左ID／属性保留。公开GeoJSON保留平面边标记，空／低维结果真实返回、clip消费者精确拒绝。GEOS前完成跨／内部图元、环闭合、输出增长与复制预算，原上限不变。48个省略投影／非空误差变体仍明确拒绝；本批不实现GEE球面默认行为，也不把显式参数子集当作完整兼容。原依赖／运行环境／用户数据保持，无新增JVM、完整Spark、浏览器、部署或Google验收；1.72MB自有临时构建已清理。总目标继续，接下来优先补普通GEE默认写法所需的球面表示、计算与下游消费者。见 [报告](../../reports/gee-python-wave60.json)、[几何语法和默认值缺口](geometry-binary.md)。

第五十九批修复复杂流程的重复标量DAG扫描与根作用域RGB／HSV展开，未增加算法名称：仍693／991（69.93%，仅入口）。完整回归 **5891 passed／27 skipped**，15个源码摘要稳定；前端11项、类型检查和临时构建通过。控制RGB往返输出图完全相同，工作量49618→36386；原先超限的HSV通道重组和Float32定标组合分别以43880／40956工作量通过，Python／JS图一致，72个合成样本单元最大误差9.72e-17。已有3×3 SVD真实秩二组合也通过原预算（45601／347节点，99有限单元最大误差4.45e-16、9缺测）；完整重建与QR残差仍分别受工作／节点预检限制。图内不可变账本、深度与强引用、64项颜色快照和独立元数据复制均有定向控制；原50000工作／500节点、来源网格证明、依赖与隔离不变。自有两次前端构建3.44MB已清理；无新增JVM、完整Spark、浏览器、部署或Google验收。默认解混瓦片等限制仍在，整体目标继续。见 [报告](../../reports/gee-python-wave59.json)、[组合语法](scalar-composition.md)。

第五十八批新增2个实际集合入口：Image.linkCollection、ImageCollection.combine，并支持官方 Python 集合 linkCollection 辅助方法。完整回归 **5861 passed／27 skipped**，16个源码／样本摘要稳定；前端11项／类型／临时构建通过。Python／JS的13项输出图一致，7组栅格输出各84个单元（66有限、18缺测）与独立预期完全一致；覆盖缺失QA、云掩膜、两种同名覆盖及嵌套实际来源的时间／足迹拒绝。名称 **693／991（69.93%）** 仅统计入口；严格唯一键、同时间／足迹和目录准入为明确本地限制。索引化逐景展开和元数据复制预充原50000预算，未改依赖或部署运行环境。自有前端临时构建1.72MB已清理；无新增原生JVM、完整Spark、浏览器、物理导出或Google验收。解混标准256²瓦片及较大组合仍待解决，整体目标继续。见 [报告](../../reports/gee-python-wave58.json)、[集合匹配语法](collection-link.md)。

第五十七批新增15个有限光谱／栅格整理入口：解混、RGB／HSV、插值／多项式、波段整理／身份／元数据及数组秩／点积／填充，含2个类型别名。完整回归 **5841 passed／26 skipped**，56个源码摘要稳定；前端11项／类型检查／临时构建通过。15个原始名称经Python客户端序列化并消费；Python／JS两景组合图一致。真实GeoTrellis解混17场景／41输出单元及两景36单元通过，同一JAR的5族回归通过。名称 **691／991（69.73%）** 仅统计入口，不是完整兼容率。

解混对未能可靠比较的候选解提前拒绝；普通三波段／三端元单纯形预算最多26像元，标准256²瓦片仍拒绝。RGB往返占49694／50000编译工作量，最大观察误差1.67e-16；两景解混最大分数误差1.39e-16。默认瓦片、较大组合、Google同数据及完整Spark／生产验收仍未完成。原预算、依赖、运行环境和用户数据保持；67源文件适配器只临时构建，自有产物已清理。见[光谱处理语法](spectral-preparation.md)、[示例62](../../examples/62_GEE_python_spectral_preparation.py)和[报告](../../reports/gee-python-wave57.json)。

第五十六批历史记录：新增34个有限元数据、要素、筛选及几何入口，包含9个比较别名。完整回归 **5648 passed／26 skipped**，前端11项／类型检查／临时构建通过；34个名称逐项经真实Python客户端序列化并计算，原17探针由2项通过提升为17项，旧50探针仍为47项通过、3项明确拒绝。Python／JS合成站点流程由12行筛选为3行，18列CSV实际写出并读回；独立字面预期与Fraction分数一致。名称 **676／991（68.21%）** 仅表示入口数量，不是完整兼容率。

类型化读取参与真实逐景元数据展开；字段选择使用有界RE2及经校验的普通字段名直接匹配。空集合先检查筛选／回调结构，不虚构数据行；可变几何重复校验，修复表格、采样、字典和列表的旧类型边界回归。缺键、身份保留和平面边类型是明确的本地政策；Filter.hasType、Geometry.projection、球面／重投影仍未支持，取样／分类表暂不接收日期筛选。原50000工作、500节点及1MB等预算保持；未改依赖或部署运行环境，无新增JVM、完整Spark、浏览器或Google同数据验收。整体目标保持进行中。 见[要素整理语法](feature-preparation.md)、[Python示例61](../../examples/61_GEE_python_feature_preparation.py)和[报告](../../reports/gee-python-wave56.json)。

第五十五批历史记录：新增2个名称入口：逐像元紧凑 QR／SVD，并扩展已有静态 Array 的矩形分解。根作用域因子引用共享不可变数值IR、元数据独立复制，使矩形SVD重建和完整2×2 LU逆组合通过原预算；更大3×3组合及QR正规残差仍明确拒绝。原生25场景／481输出单元通过，24项瓦片预算准入、1项仅内核超限边界；同一JAR的旧矩阵／因子／整数／Double／选择回归通过。修复精确输出乘积保护范围、极小有效奇异值与零空间共存、宽矩阵成本和零加微小值的问题；MC80 Jacobi最多32轮，小数位上限65536与精确输出保护分开。完整回归5500 passed／26 skipped，前端11／类型／临时构建通过；Python／JS32项图一致，合成SVD重建最大绝对误差1.07e-13。名称642／991（64.78%）仅入口统计。普通2×2 SVD预算最多572像元，当前256²瓦片不能直接通过，不是吞吐或生产验收。61源文件仅临时构建，2.48MB自有构建已清理；原64单元／50000工作／500节点及运行环境、依赖和账号数据保持。未部署，无完整Spark／浏览器／Google同数据验收，整体目标继续。见 [正交分解语法](matrix-orthogonal.md)、[示例60](../../examples/60_GEE_python_matrix_orthogonal.py) 和 [报告](../../reports/gee-python-wave55.json)。

第五十四批历史记录：新增3个名称入口：逐像元 Cholesky／LU 分解及 matrixTranspose 布局别名（2个新算法、1个别名）。L／U／P 共享一个生产者，支持因子重建、选定 U 求逆及 Cholesky 两步求解；保留原64单元／50000工作／500节点上限，完整 LU 逆组合仍明确超限。修复有理数1/3截断制造奇异矩阵伪主元、常量／参考二次舍入和空包络扩大负指数范围的问题。实际 GeoTrellis 的18场景／18输入像元／285输出单元、7项非法规格、5项非零及6项包络控制通过，同一JAR的旧矩阵／整数／Double／选择回归通过。完整回归5403 passed／25 skipped，前端11／类型／临时构建通过；Python／JS10项图一致，229个有限合成图数值最大绝对误差3.11e-15，另计1个末端Float32 Infinity。名称640／991（64.58%），仅入口统计。LU精确有理数预算按实际源指数包络预充；普通2×2整数128²和小数256²瓦片预算允许，极端指数4²像元拒绝；RDD准入仅静态审查，非吞吐或CPU硬界证明。56源文件适配器仅临时构建，3.12MB自有构建及5366字节工作流临时文件已清理，未改依赖、安装环境或账号数据。未部署，无完整Spark／浏览器／物理导出／Google同数据验收，整体目标保持进行中。见 [分解语法](matrix-factors.md)、[示例59](../../examples/59_GEE_python_matrix_factors.py) 和 [报告](../../reports/gee-python-wave54.json)。

第五十三批历史记录：新增2个入口：Image.matrixInverse／matrixPseudoInverse，并扩展matrixSolve的逐像元动态、欠定、秩亏及宽矩阵路径。共享原生生产者按行优先输出，保留显式Float32／Double舍入、整体掩膜、来源和元数据；原64单元／50000工作／500节点上限不变。修复RHS归一化抹去极小信号、大基线抵消及非首块瓦片尺寸绕过预算的问题。实际GeoTrellis的19场景／24输入像元／150输出单元通过，16项非法规格及瓦片／阈值／非零控制通过，旧整数、22种Double运算和三元选择回归通过。完整回归5342 passed／24 skipped，前端11／类型／临时构建通过；Python／JS11项输出图一致，140个有效合成图数值的最大绝对误差4.44e-16。名称637／991（64.28%），仅入口统计。2×2求解预算允许128²瓦片但拒绝256²；末端Float32转换可溢出为Infinity，已明确记录并验证，不能宣称整体数值兼容。54源文件适配器仅临时构建，2.39MB自有产物已清理，未改依赖、安装环境或账号数据。未部署，无完整Spark／浏览器／物理导出／Google同数据验收，整体目标保持进行中。见 [矩阵语法](pixel-matrices.md)、[示例58](../../examples/58_GEE_python_pixel_matrices.py) 和 [报告](../../reports/gee-python-wave53.json)。

第五十二批历史记录：扩展3个已有API：Double数组排序、首个最大值坐标及Double载荷where。值／键精度分别保留，修复普通掩膜在缺失条件键时保留载荷的根因，改用有界原生select／where_select三元算子；同条目资产网格冲突新验证，保留原数组／工作／图上限。实际GeoTrellis的5场景／40像元逐位一致，16项非法规格和6项非法瓦片控制通过；旧22种Double运算及整数／QA原生回归通过。完整回归5260 passed／23 skipped，前端11／类型／临时构建通过；Python／JS6项输出图一致，39个有效样本值与独立参考完全一致。名称仍635／991（64.08%），仅入口统计。初次完整测试被命令沙箱权限拦截，保留失败证据后以所需权限运行原测试通过，无源码放宽。51源文件适配器仅临时构建，2.34MB自有产物已清理，运行环境／依赖／账号数据未改。未部署，无完整Spark／浏览器／物理导出／Google同数据验收，整体目标保持进行中。见 [Double排序／选择语法](double-array-selection.md)、[示例57](../../examples/57_GEE_python_double_selection.py) 和 [报告](../../reports/gee-python-wave52.json)。

第五十一批历史记录：扩展7个已有API的Double数组／矩阵能力，并串联预测、选择和属性复制。固定大基线样本的最大斜率误差从6.10e-5降至1.11e-16；幅度保护保留极值回退。有界来源缓存使三景Double回归残差在原预算内完成（21151工作量／190节点），独立RMS误差1.78e-15。完整回归5181 passed／22 skipped，前端11／类型／临时构建通过；Python／JS6项图一致。名称仍635／991（64.08%），仅入口统计。原64元素／50000工作／500节点上限保持，最大形状的完整导出仍可超限；源无穷值拒绝与运算溢出缺测分开验证。原生51源文件未改，未重复构建或部署；临时产物已清理，用户数据与依赖未改。无完整Spark／浏览器／Google同数据验收，整体目标保持进行中。见 [Double数组语法](double-raster-arrays.md)、[示例56](../../examples/56_GEE_python_double_matrix.py) 和 [报告](../../reports/gee-python-wave51.json)。

第五十批历史记录：扩展已有 **22种基础运算的原生 Double 路径**，使整数／QA、温度换算、NDVI及距离结果可继续计算；未增加名称入口。实际GeoTrellis的25场景／173像元、6步组合／44像元全部通过，最大观察误差1 ULP；旧整数／QA内核回归通过。固定双元素数组四则运算及三景过原点回归系数另有独立合成图数值证明，残差分支仍因编译预算拒绝，不宣称完整Double数组／矩阵兼容。完整回归 **5110 passed／22 skipped**，前端11／类型／临时构建通过，Python／JS11项组合图一致。名称 **635／991（64.08%）** 仅统计入口。常量嵌套类型转换、掩膜、网格和原资源上限保持；51源文件适配器只做可信组件构建，临时产物已清理。52条既有上游提示保留，依赖、安装环境和数据未改。未部署，无完整Spark／浏览器／Google同数据验收，整体目标保持进行中。见 [Double算术语法](float64-arithmetic.md)、[示例55](../../examples/55_GEE_python_float64_analysis.py) 和 [报告](../../reports/gee-python-wave50.json)。

第四十九批历史记录：新增 **35个整数影像名称入口（含21个同义别名）**：7种整数范围转换和7种QA位操作，并扩展已有6种Float64比较。实际GeoTrellis的26场景／214像元、10步合成QA链／13像元、36项非法wire／10项非法像元／5项全掩膜参数及5项转换控制通过；修复有效Int.MinValue转Double时丢失及常量折叠精度标记丢失。公共复制路径涉及的5族原生回归12项通过。完整回归 **4990 passed／21 skipped**，前端11／类型／临时构建通过，Python／JS16项组合输出一致。名称 **635／991（64.08%）** 仅统计入口，不是完整兼容率。整数结果物理Double、int64限±2^53、向零截断与移位政策均明确；上游dry-run仅保留已知输出结构和来源，实际输入校验延后到真实立方体。通用Float64算术／Google／完整Spark与部署仍未验收；52条上游提示保留，依赖、安装环境和数据未改。整体目标保持进行中。见 [整数／QA语法](integer-images.md)、[示例54](../../examples/54_GEE_python_integer_images.py) 和 [报告](../../reports/gee-python-wave49.json)。

第四十八批历史记录：新增有限 `Image.fastDistanceTransform`：默认256像元邻域、三种度量及直接 sqrt／阈值组合。整数包络与方向扫描按窗口像元线性计算，多跳目标片段保留已有空间／时间键。13项纯变换与16项真实GeoTrellis源瓦片场景通过，85个观察键／1,772,714输出像元的完整瓦片摘要匹配独立Python参考；三种默认3×3瓦片场景和跨两块瓦片的时间隔离均通过。完整回归 **4855 passed／20 skipped**，前端11／类型／临时构建通过。名称 **600／991（60.54%）** 仍仅为入口统计。无目标截断、掩膜目标、多波段和dtype为明确本地政策，尚无Google对照；256方瓦片默认邻域最多接纳24个键，不代表吞吐。52条上游提示单列，依赖／安装环境／用户数据未改；临时产物已清理，未部署，无完整Spark验收。见 [快速距离语法](fast-distance.md)、[示例53](../../examples/53_GEE_python_fast_distance.py) 和 [报告](../../reports/gee-python-wave48.json)。

第四十七批历史记录：新增有界 `Image.distance`：原始欧氏／曼哈顿／棋盘距离核，0–16像元半径，逐波段非零目标、掩膜及时间键隔离。修复选景／裁切／掩膜时过早 Float32 转换导致微小非零目标丢失，以及合法第500节点被提前拒绝。Python／JS九组编译图一致；实际 GeoTrellis 的14场景在两条路径各比较660个输出像元，与独立参考一致（欧氏0 ULP）。完整回归 **4765 passed／19 skipped**，前端11／类型／临时构建通过；51条既有 Rasterio 弃用提示保留。名称 **599／991（60.44%）** 仅统计入口。米单位、变换后距离核、fastDistanceTransform、通用 Float64 算术与完整Spark／部署／Google对照仍未完成；原有预算保持，256方瓦片半径16时最多接纳欧氏18／曼哈顿27／棋盘13个键，并非吞吐承诺。未修改依赖、安装运行环境或用户数据。见 [距离语法](distance.md)、[示例52](../../examples/52_GEE_python_distance.py) 和 [报告](../../reports/gee-python-wave47.json)。

第四十六批历史记录：接通版本化本地 `cop-dem-glo-30` 高程目录：源网格裁切、尺度／单位／掩膜校验、NaN COG 与来源记录。Python／JS六组流程图一致；两种坐标系的实际 COG→GeoTrellis 地形内核→GeoTIFF 读回比较 **1536 像元**，最大角度误差3.72×10⁻⁹°，阴影精确一致。完整回归 **4685 passed／18 skipped**，前端11／类型／临时构建通过；51条 Rasterio 弃用提示单列。名称仍 **598／991（60.34%）**，本批不增加算法入口。原工作预算不变，目录全量元数据扫描通常只能容纳几十条密集轮廓；Google别名、通用上传DEM、完整Spark／部署／真实数据验收仍未完成。未改依赖、安装环境或用户数据，临时产物已清理。见 [DEM合同](local-dem.md)、[示例51](../../examples/51_GEE_python_local_dem.py) 和 [报告](../../reports/gee-python-wave46.json)。

第四十五批历史记录：新增 **6个有限入口（含1个弃用别名）**：Terrain产品／坡度／坡向／阴影及 neighborhoodToBands。Python／JS十八项组合图一致；真实GeoTrellis地形14场景在两条路径各比较504像元，最大角度误差5.56×10⁻⁹°；邻域展开6输出／384像元精确匹配。完整回归 **4630 passed／17 skipped**，前端11／类型／临时构建通过。名称 **598／991（60.34%）** 仅为入口统计，原50探针47编译／3拒绝。修复极端高程差误归零、微小角度和过早节点限额；原预算保持，业务模块分为独立参数／度量／数值／预算／适配层。生产EE DEM目录适配仍待完成，现有目录准入不变；合成高程测试不表示真实DEM已接入。切平面弦长度量、阴影Float64和邻域命名为明确本地政策。未改依赖／安装环境／数据，临时产物已清理；无完整Spark／部署／Google同数据验收。见 [地形语法](terrain.md)、[原生边界](terrain-native.md)、[邻域波段](neighborhood-bands.md)、[示例50](../../examples/50_GEE_python_terrain.py) 和 [报告](../../reports/gee-python-wave45.json)。

第四十四批新增 **7个有限入口**：三种距离核、Compass／Kirsch、Kernel.inverse 和邻域专用 Reducer.unweighted；扩展 reduceNeighborhood 的12种统计及共享输入多输出组合。Python／JS十八项组合图一致；真实GeoTrellis与独立Fraction／Decimal参考验证19场景，两条路径各456像元、4个时间键，31源文件适配器构建通过。完整回归 **4556 passed／15 skipped**，前端11／类型／临时构建通过。名称 **592／991（59.74%）** 仅为入口统计，原50探针47编译／3拒绝。修复组合权重互相影响、工作预充和标准差预算漏算；原上限不变。单位3×3均值在256方瓦片通过，3×3方差在128方通过、256方超限；密集7×7均值超限。二值有效性、空支持NoData、众数并列和分数半径为明确本地政策。未改依赖／安装环境／数据，临时构建已清理；未部署，无完整Spark／浏览器／Google同数据验收。见 [邻域统计](neighborhood-statistics.md)、[原生边界](neighborhood-native.md)、[距离核](distance-kernels.md)、[示例49](../../examples/49_GEE_python_local_texture.py) 和 [报告](../../reports/gee-python-wave44.json)。

第四十三批新增 **9个有限入口**：Image.convolve、高斯／5种边缘核、Kernel.rotate／add。Python／JS十五项组合图一致；真实GeoTrellis与独立Fraction参考验证11场景、两条路径各272像元，25源文件适配器构建通过。完整回归 **4434 passed／14 skipped**，前端11／类型／临时构建通过。名称 **585／991（59.03%）** 仅为入口统计，原50探针47编译／3拒绝。修复多波段筛选的dry-run元数据拒绝，实际上游进程求值器验证focal／convolve输入边界。保留原预算；256方瓦片的3×3核通过、密集7×7核超限。有符号归一化和米单位明确拒绝；高斯半径、Roberts焦点及完整邻值掩膜为已说明的本地政策。依赖、安装环境和数据不变，临时构建已清理；未部署，无完整Spark／浏览器／Google同数据验收。见 [卷积语法](convolve.md)、[加权核](weighted-kernels.md)、[原生边界](convolve-native.md)、[示例48](../../examples/48_GEE_python_convolution.py) 和 [报告](../../reports/gee-python-wave43.json)。

第四十二批新增 **19个有限邻域入口（含5个别名）**：8种Kernel构造、5种focal滤波及reduceNeighborhood。Python／JS十二项组合图一致；独立Fraction基准与真实GeoTrellis缓冲验证33场景、两条路径各792像元，22源文件完整适配器构建通过。完整回归 **4321 passed／13 skipped**，前端11／类型／临时构建通过；最终原生零半径修复另有定向验证。名称 **576／991（58.12%）** 仅为入口统计，原50探针47编译／3拒绝。保留Float64、掩膜和时间键；导出区域与分辨率不会提前改变邻域输入。仅像素单位，非零半径须小于瓦片短边；米单位、非均匀权重和其余邻域功能仍受限。依赖、安装环境和数据不变，临时构建已清理；未部署，无完整Spark／浏览器／Google同数据验收。见 [邻域语法](focal.md)、[原生边界](focal-native.md)、[Kernel](kernels.md)、[示例47](../../examples/47_GEE_python_neighborhood.py) 和 [报告](../../reports/gee-python-wave42.json)。

第四十一批新增 **8个有限分布统计入口**：百分位数、区间均值、众数、偏度／峰度及三种圆周统计。完整回归 **4207 passed／12 skipped**，前端11／类型／临时构建通过；Python／JS十二项组合输出一致，两行分组CSV实际写出并读回。名称 **557／991（56.21%）** 仅为入口统计。八种1000值列表和500行表格通过，1000行表格仅众数通过，其余按原50000工作预算拒绝。插值、并列值、总体矩和不确定方向的本地规则已说明；显式直方图近似参数、权重、这些新增归约的Array／栅格／动态表路径拒绝。依赖、安装环境和数据不变，临时构建已清理；未部署，无Google同数据或生产验收。见 [百分位数](quantile-reducers.md)、[矩统计](moment-reducers.md)、[圆周统计](circular-reducers.md)、[示例46](../../examples/46_GEE_python_distribution_summary.py) 和 [报告](../../reports/gee-python-wave41.json)。

第四十批扩展已有数值归约的实际上下文：product、总体标准差／方差、样本方差及 minMax 接通影像波段、时间轴和数组，多输出支持共享输入 combine／setOutputs 与 fieldAxis。完整回归 **4078 passed／12 skipped**，前端11／类型／临时构建通过；Python／JS五项组合输出一致，实际 GeoTrellis 瓦片7种归约、41个像元及8项拒绝控制通过，19源文件完整适配器构建通过。修复极大共同偏移／微小差值的标准差、乘积中间溢出、选景及掩膜的 Float64 精度；跨观测需明确 STAC 网格证据。名称仍 **549／991（55.40%）**，仅统计入口，本批未增加名称。单波段方差50景生成351节点，100景触及原500节点上限。依赖、安装环境、数据与预算不变，临时构建已清理；未部署，无完整Spark／任务导出／浏览器／Google同数据验收。见 [栅格统计](raster-statistics.md)、[静态数组](array-statistics.md)、[栅格数组](raster-array-statistics.md)、[示例45](../../examples/45_GEE_python_raster_statistics.py) 和 [报告](../../reports/gee-python-wave40.json)。

第三十九批历史记录：新增 **10个有限统计归约入口**：Pearson／Spearman／Kendall相关性、Sen趋势、向量协方差、固定一维／二维直方图及列表／要素收集。完整回归 **3983 passed／11 skipped**，前端11／类型／临时构建通过；Python／JS十五项组合输出一致，统计摘要1行与收集表6行CSV实际写出并读回。名称 **549／991（55.40%）** 仅为入口统计，不代表完整语义兼容。保留原50000工作预算；1000行Pearson、二维向量协方差、固定直方图和toList通过，部分排序／成对算法及toCollection在该规模超限。已修复大偏移中心化、零／次正规数中位排序与p值尾部精度问题。部分默认结果名、协方差归一化及Sen截距采用明确的本地政策，Google同数据验证仍缺；依赖与运行环境未变，本批未部署。见 [相关性与趋势](correlation-reducers.md)、[协方差](covariance-reducers.md)、[固定直方图](fixed-histograms.md)、[收集归约](collecting-reducers.md)、[示例44](../../examples/44_GEE_python_trends_and_distributions.py) 和 [报告](../../reports/gee-python-wave39.json)。

第三十八批历史记录：新增 **20个有限归约入口（含2个已弃用别名）**：总体／样本方差、minMax、乘积、计数／频数表、逻辑／位归约及 repeat／forEach。完整回归 **3843 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS二十三项结果一致，两行分组CSV实际写出与结果读回通过。名称 **539／991（54.39%）** 仅为入口统计，不代表完整语义兼容。countEvery 保持零输入列，重复值频数表避免重复输出计费，1000行重复值通过原50000预算；1000个不同值的完整表格路径仍超限。依赖及运行环境未变，Google／真实数据／生产验收仍未完成。见 [数值归约](numeric-reducer-leaves.md)、[离散归约](discrete-reducer-leaves.md)、[多列归约](reducer-expansion.md)、[示例43](../../examples/43_GEE_python_reducer_statistics.py) 和 [报告](../../reports/gee-python-wave38.json)。

第三十七批新增 **28个有限计算入口**：DateRange9、属性统计14、组合归约4、集合flatten1，并扩展构造／map及List.reduce／reduceColumns。完整回归 **3722 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十四项结果一致，两行分组CSV通过合成dispatch／worker／实际写出与结果读回。名称 **519／991（52.37%）** 仅为入口统计，不代表完整语义兼容。1000行统计在原50000预算内通过；新增模块按描述／校验／计算／输出拆分，依赖及运行环境未变。未部署，Google／真实数据／生产验收仍未完成。见 [嵌套集合](nested-collections.md)、[属性统计](aggregate-statistics.md)、[分组归约](composed-reducers.md)、[日期区间](date-ranges.md)、[示例42](../../examples/42_GEE_python_grouped_tables.py) 和 [报告](../../reports/gee-python-wave37.json)。

第三十六批新增 **14个有限静态入口**：UTC日历4、Array选择3、内联表3、Number.expression1、String正则3，并扩展已有Dictionary.select/remove的RE2正则选择。完整回归 **3644 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十三项结果一致，两行CSV通过合成dispatch／worker／结果读回。名称 **491／991（49.55%）** 仅为入口统计，不代表完整语义兼容。固定RE2依赖的OSV／PyPI已知告警查询为0，原锁定包版本未变；50000工作预算保持。未启动或部署业务服务，Google／真实数据／生产验收仍未完成。见 [日期](date-calendar.md)、[表达式](number-expression.md)、[正则](string-regex.md)、[数组选择](array-selection.md)、[表格](feature-table-selection.md)、[示例41](../../examples/41_GEE_python_metadata_tables.py) 和 [报告](../../reports/gee-python-wave36.json)。

第三十五批新增 **61个有限静态入口**：Number类型转换24、Array类型转换26、特殊函数8、容器筛选3，包含25个单列别名。最终完整回归 **3409 passed／10 skipped**，前端11／类型／临时构建通过；Python／JS十一项输出一致，三行CSV通过合成dispatch／worker／结果读回集成。名称 **477／991（48.13%）** 仅为入口统计。原预算保持，未改依赖或重建JVM，未启动业务服务；没有新增栅格／浏览器／生产／Google验收。整数舍入推断、Int64精确域和正则等限制单列，整体目标仍进行中。见 [Number转换](number-casts.md)、[Array转换](array-casts.md)、[特殊函数](static-special-math.md)、[容器筛选](container-selection.md)、[示例40](../../examples/40_GEE_python_numeric_preparation.py) 和 [报告](../../reports/gee-python-wave35.json)。

第三十四批并行新增 **39个入口**，含16个实际Image科学函数、Array位运算／向量／padding及Number解析／别名。冻结便携 **3180 passed／10 skipped**（另排除4项延期原生测试），七个可信JVM／GeoTrellis组件、前端11／类型／构建通过；Python／JS十项组合输出一致。名称入口 **416／991（41.98%）**，其中本批12个为官方单列别名，不是完整参数／语义／Google兼容率。修复常量数学逐景绑定、不同atan2来源隐式重采样和4000景普通map的新增预算开销，原预算不提高。Float32精度和极点政策明确；未部署，无完整Spark／服务／浏览器／Google验收。见 [影像数学语法](pixel-math.md)、[示例39](../../examples/39_GEE_python_pixel_math.py)、[报告](../../reports/gee-python-wave34.json)。

第三十三批按5个算子族批量新增 **98个实际计算入口**：Number25、Array36、List18、Dictionary10、String9。冻结便携回归 **2989 passed／9 skipped**（另排除4项延期原生测试），前端11／类型／临时构建及Python／JS的10项组合输出通过；保留50000工作／1MB输出等上限，纯静态批次不重复构建未改动的JVM。新List严格整数校验采用显式模式，保留历史结构比较。名称入口 **377／991（38.04%）**，包括官方单列别名，不代表完整参数／运行时或Google兼容率。新能力不自动开放同名Image栅格算子；旋转、碰撞、Unicode等局部政策有明确边界。未部署。见 [批量语法](static-families.md)、[示例38](../../examples/38_GEE_python_static_families.py)、[报告](../../reports/gee-python-wave33.json)。

第三十二批新增有限 `Classifier.explain()`：真实 Smile 模型的重要性、实际树数和原始袋外错误率，以及有界字典读取／独立JSON任务。冻结源码完整回归 **2788 passed／3 skipped**（另排除4项延期原生测试），六个可信组件及前端11／类型／临时构建通过；另补2项静态控制流精确图测试。三棵可手算树实际返回重要性 `[0,1.5]`、树数3、OOB0，物理JSON读回和任务权限验证通过。入口 **279／991（28.15%）** 仅统计名称，参数／计算语义仍受限；原50定向探针45编译不表示90%任意迁移成功率。原始Smile无袋外投票时也可能返回0，不宣称Google一致性或真实模型能力。复审修复了普通大列表／表格被新检查提前超限的问题，保留原测试样本和预算。未部署，无完整Spark／批任务／浏览器／Google验收。见 [解释语法](rf-explanation.md)、[示例37](../../examples/37_GEE_python_rf_explanation.py)、[报告](../../reports/gee-python-wave32.json)。

第三十一批接通RF分类后filter／无排序limit／randomColumn，继续支持errorMatrix／getInfo／CSV；前后操作合计16步，累计50000表预算与RF150000分开，64项弱身份校验缓存避免重复扫描。冻结兼容源码完整回归 **2690 passed／3 skipped**（另排除4项延期原生测试），六个可信JVM／栅格组件、前端11／类型／临时构建通过。真实显式单预测字段模型的32行预测→16行留出→16行随机列→8行限量，独立ID／像元中心几何／哈希／矩阵频数及物理JSON／CSV读回通过；合成样例不代表预测能力。入口仍 **278／991（28.05%）**，仅名称统计。本批未部署，无完整Spark／批任务／浏览器／Google验收；其他模式、map／排序／再次训练、邻域、高级时序及完整API继续。见 [分类后语法](classified-tables.md)、[示例36](../../examples/36_GEE_python_classified_tables.py)、[报告](../../reports/gee-python-wave31.json)。

第三十批历史记录：支持MD／RF训练省略或null的 `inputProperties`：仅按真实集合声明 `band_order` 选择完整有序字段，显式列表优先，不猜首行字段或擅自去掉类别。内联集合元数据在筛选／限量／随机列／map到Feature中保留，扫描和复制在分配前独立计费。冻结源码完整回归 **2640 passed／3 skipped**（另排除4项延期原生测试），六个可信JVM／栅格组件与前端11／类型／构建通过；编译器的自动规格实际进入Smile模型。入口仍 **278／991（28.05%）**，本批只扩展已有API参数行为；原50探针45编译／5拒绝不变。见 [训练字段语法](training-schema.md)、[示例35](../../examples/35_GEE_python_training_schema.py)、[报告](../../reports/gee-python-wave30.json)。未部署，无完整Spark／批任务／浏览器／Google验收；v1取样仍需显式字段，其他模式及完整API目标继续。

第二十九批历史记录：新增有限 `FeatureCollection.randomColumn`，并接通 `sample／sampleRegions → 随机划分 → 显式 schema RF 训练 → 要素预测／验证矩阵`。新增或覆盖字段经过编译、引擎、getInfo 和 CSV 的完整 schema 传递；修复了 Image.sample 的 band_order 元数据被 RF 训练误拒绝的问题。冻结源码完整回归 **2600 passed／3 skipped**（另排除4项延期原生测试），六个可信独立 JVM／栅格组件通过；真实 Py4J 链路得到32行样本、16／16互斥完整划分及实际训练／验证频数。前端11／类型检查／构建通过，未部署。入口 **278／991（28.05%）** 仅统计名称，部分参数、数值和服务仍受限；本地SHA256随机序列不承诺Google一致。见 [随机划分语法](random-split.md)、[示例34](../../examples/34_GEE_python_random_split.py)、[报告](../../reports/gee-python-wave29.json)。完整Spark／批任务／浏览器／Google验收仍未运行。

第二十八批历史记录：新增有限实际 `Image.sample`，支持全像元、factor／近似 numPixels、固定本地随机种子、缺测保留／删除、像元中心几何与 band_order。冻结源码回归 **2493 passed／3 skipped**（另排除4项延期原生测试），前端11／类型检查／构建通过；五个可信独立 JVM／栅格组件通过。取样内核与独立网格／哈希参考对比，已有 getInfo／CSV、filter／limit 和显式 schema 分类链路继续可用。入口 **277／991（27.95%）** 只统计名称，部分参数和数值语义仍受限。见 [语法](image-sampling.md)、[示例33](../../examples/33_GEE_python_image_sample.py)、[报告](../../reports/gee-python-wave28.json)。该批未验收Google抽样序列、完整Spark／部署／浏览器；随机列由第二十九批接续，邻域和自动训练schema仍待实现。

第二十七批补齐真实 RF 要素分类、训练重代入与验证矩阵的七种访问器。完整便携回归 **2413 passed／3 skipped**（另排除4项延期原生测试），前端11／类型检查／构建通过；实际 JVM 要素预测、训练频数及四个栅格组件通过。支持内联及固定取样表；`getInfo()` 走受任务权限保护的 JSON 结果，分类表继续支持 CSV。相同训练／预测取样 IR 复用固定来源分支，空表不产生假行，零分母明确失败。新增内容扩展了已有 API 的运行语义，入口仍为 **276／991（27.85%）**，不能作为完整兼容率。见 [要素验证语法](rf-validation.md)、[示例 32](../../examples/32_GEE_python_rf_validation.py) 和 [报告](../../reports/gee-python-wave27.json)。完整 Spark／部署／浏览器／Google 对照仍未验收。

第二十六批 [报告](../../reports/gee-python-wave26.json) 与 [RF语法文档](random-forest.md)：新增实际 Smile1.5.3 随机森林，内联／采样表运行时训练、影像分类、六参数、独立 SPI／依赖锁与对象类型边界。完整回归 **2293 passed／3 skipped**（另排除4项延期原生测试），前端11／构建通过；新增3项Python／JS SDK图一致性，四个真实tile组件通过。1000×8／100树的真实组件训练与256²像元预测通过；Unicode名称码点控制另有最终定向核验。入口 **276／991（27.85%）** 只表示名称，参数／数值仍有明确限制；RF explain／表分类／混淆矩阵／随机列／其他模式／band_order推断尚未实现，完整Spark／部署／浏览器／真实数据／Google对照仍未验收。


第二十五批 [报告](../../reports/gee-python-wave25.json)：新增标签 Image.remap、受限 Filter.expression、取样表 filter／无排序 limit 及累计资源计费。示例 30 的标签掩膜、17 个几何候选位置、15 行有效样本、14 行 notNull、11 行条件通过和 8 行限量训练，以及三度量预测，有独立原始网格参考。便携 Python **2068 passed／3 skipped**（另排除 4 项原生测试），前端 **11 passed**／构建通过，SDK 图一致性 **77**，真实 tile 内核通过。入口 **275／991（27.75%）** 只表示名称，不是完整参数或计算兼容率。完整 Spark／部署／浏览器／真实数据／Google 验收未运行；[该批尚未实现随机森林](random-forest-roadmap.md)。

第二十四批 [报告](../../reports/gee-python-wave24.json) 与 [取样语法文档](sampling.md)：接通有限 sampleRegions、实际样本运行时训练、栅格分类与样本 getInfo／CSV 任务合同。便携 Python **1882 passed／3 skipped**（另排除 4 项原生测试）、前端 **11 passed**／构建通过，Python／JS 官方客户端一致性 **72** 项；取样与分类的可信独立 JVM tile 内核均通过。API 名称入口 **273／991（27.55%）**，参数和数值语义仍需逐项验证；此数值不代表完整兼容率。完整 Spark cube、部署／浏览器、真实数据和 Google 对照未运行。
状态：2026-10-24，第五十八批已验证，整体兼容目标尚未完成。

第二十三批 [验证报告](../../reports/gee-python-wave23.json)：新增有限 `Image.classify` 的 schema 选择、精确模型编译、Python 桥与真实 GeoTrellis tile 内核，训练仍使用内联要素。macOS ARM64 Python **1751 passed／3 skipped**（启用可信独立 JVM 内核测试，另排除 4 项原生运行测试），前端 **11 passed**、TypeScript／构建通过；较[第二十二批](../../reports/gee-python-wave22.json)增加 66 项通过。独立 tile 内核是组件运行证据，完整 Spark cube、沙箱任务、HTTP／浏览器、部署和 Google 对照均未在本批验收。

S＝官方客户端实际序列化；C＝本地编译；E＝实际栅格引擎；N＝独立数值基准；G＝Google 同数据对照。静态数值求值和合成图测试分别说明，不能标成原生栅格 E。固定的 991 项签名、方法可见数量和定向探针计数均不能换算为全 API 兼容百分比。

当前阶段按用户要求暂缓 Linux 隔离执行、macOS／ARM64 和本机真实数据验收，优先完成 Python API／参数／计算语义，再推进 JS。新增能力继续用版本化合成样本、独立数值参考及已有便携测试验证；延期项目不是本阶段前置条件，现有运行器与沙箱检查保留。

已有项目与可复用边界见 [生态核对](ecosystem.md)：本地脚本宿主、Google 客户端封装、独立本地计算后端与完整 EE 服务端兼容分别核对，不据项目名称或一次检索判断其兼容范围。

## 全量目录

[机器可读 Python API 清单](../../reports/gee-python-api-inventory.json) 包含 991 项固定算法签名、2,451 项算法参数、48 项公开 Python 类记录及 1,797 项 callable 签名记录，包括继承方法、参数种类／默认值、opt_* 别名、嵌套导出类和绑定来源。939 项算法找到了明确的 Python 命名绑定；其余 52 项标为未解析映射，仍可通过通用 ApiFunction 调用，不能据此判定后端不支持。

记录类型／方法存在和验证其计算行为是两件事；每项原始官方参数保留顺序、默认值和可选标志。公开云端 transport／OAuth 方法列入目录用于完整追踪，本地运行时仍禁用这些路径。生成器要求独立、未配置本地会话的 SDK 进程，避免本地适配替换方法后生成不完整目录。

## 已验证及待完成

- [x] 有限逐像元紧凑QR／SVD及静态矩形分解；保留整体掩膜、显式精度、精确秩和有界资源。根作用域因子共享使矩形重建与2×2完整LU逆可编译；更大组合、默认瓦片和Google等价限制单列。

- [x] 训练字段省略／null仅从已声明band_order读取；内联集合元数据及复制／行操作／CSV合同，自动与显式编译规格及实际JVM衔接分别验证。
- [x] 有限 randomColumn 的 uniform／normal、signed64种子、显式行键、新增／覆盖列和采样后训练／验证划分；本地RNG序列与Google是否相同未验证。
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
- [x] 有限 minimumDistance 欧式／曼哈顿／cosine 光谱角的实际类均值训练、唯一最近类预测、schema／默认模式、内联要素分类及真实重代入混淆矩阵；独立训练／验证样本、均值／距离和误差指标参考。
- [x] 有限 Image.classify 接入训练后的 minimumDistance，schema 按名称选取／排列，保留精确分数类中心、输入实际精度与掩膜；三种度量的合成图 N 和真实 JVM tile 内核独立参考通过，完整 Spark／运行器验收另记。
- [x] 有限内联 FeatureCollection 的本地 CSV 批导出；Python 官方 Task 与 JS Export.table wrapper 串联真实 CSV 写出／发布／读取的可信合成验证，保留 selectors、身份、元数据和权限。
- [x] 有限栅格 linearRegression 的过原点／单位截距模型、1..4 响应、联合完整行、系数／RMS 数组；有限多数组波段选择／元数据，双响应分字段物化和独立 SVD／空间掩膜参考。
- [x] 延迟单波段维度／改名元数据，保留数值与源／掩膜／类型边界；共享表达式标签、完整四系数／双响应预测、同日／重复观测及超限控制。
- [x] 静态方阵 QR／LU／SVD 真实分解与因子字典组合；部分选主元、退化正交分解、资源预充，以及合成光谱混合／噪声丰度的独立分数参考。
- [x] 单数组波段的真实 toFloat，以及静态满列秩设计的有限 Image.matrixSolve；栅格多响应、整体缺测掩膜、显式精度和预算拒绝；合成光谱估计／重建／残差的独立分数参考。
- [x] 有限 ImageCollection.toArrayPerBand 的定长逐波段堆叠、静态 Image.arrayReshape 和 Number.sin／cos；集合日期驱动的谐波设计与栅格最小二乘链路，参数与数值边界见下文。
- [x] 有限静态 Number／Array.hypot／atan2，以及由既有像素算子计算的 Image.hypot；独立高精度范数／方向角参考，串联谐波系数的真实振幅输出，轴约定与 Float32 溢出边界明确登记。
- [x] 单数组 Image.arrayCat／arrayRepeat 的真实轴布局、有效常量 Image 重复次数、共同掩膜和预算拒绝；双独立响应最小二乘工作流的系数／拟合／残差与 Fraction／SVD 参考一致。
- [x] 固定矩阵 Image.matrixDiagonal／matrixToDiag／matrixTrace／matrixDeterminant 的真实单元操作或 Float32 算术；四景双波段样本协方差、对角／迹／行列式工作流与 Fraction／NumPy 参考一致。
- [x] 固定 Float32 数组的 Image.arrayAccum 前缀 sum／min／max 与稳定缩放 Image.matrixFnorm，补单数组选择／改名；跨年同日多景累计异常、严格相对误差范数和缺测／预算控制。
- [x] Array.sort／Image.arraySort 的真实按键排序和成组切片置换；质量排序保留 NDVI／日期配对，独立分数及 Float32 参考核对并列、同日多景和完整掩膜。
- [x] 有限 ConfusionMatrix 逐类 consumersAccuracy／producersAccuracy／fscore；精确分数中间量及训练／验证表组合，返回形状和 Fβ 轴方向是明确的本地政策，未验证 Google 等价。
- [ ] 每一签名／参数组合的 S／C、适用的独立 N，以及负向、缺测、边界验收；E 按现有环境可用条件单独记录。
- [ ] 动态形状、其余多数组波段运算和 Image.array*、通用设计矩阵的逐像元回归、采样／其余图像分类器及模式、矢量／空间和多重／歧义度量 Join、其余邻域／距离及高级时序。
- [ ] 后续阶段：Linux 执行／隔离适配、macOS Seatbelt、ARM64 JNI 和本机真实数据验收；当前阶段延期。
- [ ] Google 同数据数值比较按可取得条件另记；本机真实完整项目验收延期。

既有本机 Python 地图、任务、GeoTIFF／CSV 和下载证据见 [Python 客户端报告](../../reports/gee-python-client.json)；本次 Linux 工作没有重新执行这些本机流程，也没有复制本机账号或影像。

## 本轮新增能力的准确边界

| 能力 | 本次证据 | 尚未覆盖 |
| --- | --- | --- |
| 嵌套集合与属性统计 | S/C 与独立静态 N；Collection 构造／map 返回子集合后 flatten，14种 aggregate 统计实际字段，Python／JS 分组表及合成 CSV 工作流 | <=1000行，共享预算；outer 元数据保留、child 元数据丢弃为本地规则；混合／动态子集合拒绝，影像 aggregate 仅读取已声明元数据，无 G |
| 组合与分组归约 | S/C 与独立静态 N；combine／group／setOutputs／getOutputs，List.reduce 与内联 reduceColumns 的真实标量／行回归组合 | 描述树64节点／深度16／32输入／256输出；权重、repeat、栅格／运行时表消费者拒绝；空值、分组顺序与碰撞政策见 [语法](composed-reducers.md)，无 G |
| DateRange | S/C 与独立区间参考；9种访问、布尔及交并方法，数值转换前验证精确域 | 有限UTC毫秒±2^53；无界区间端点／直接JSON／日期过滤拒绝；空区间政策尚无G，见 [语法](date-ranges.md) |
| Python GeoJSON | S/C，有限二维 WGS84 几何；类型化 EE 默认测地线、evenOdd／left-inside 及集合继承经固定 S2 验证，显式平面边保留 GEOS 路径 | 非 WGS84、重投影容差、公开全球几何编码仍不支持；3项严格球面精度控制未通过；旧栅格／筛选的无标记输入仍按平面处理，无完整 E/G |
| Filter.notNull | S/C，最多 1000 个平面属性名，共享 50000 步预算 | 嵌套属性选择器、Google 对照 |
| Dictionary／List | S/C；NumPy linspace／Python range 独立静态参考；空 keys 和缺键默认值回归 | 完整所有方法和类型强制转换；分数步长按生成 Float64 值比较端点，无 G |
| 有限 Join | S/C，simple／inverted／saveFirst／saveAll／saveBest／inner；maxDifference 可与标量条件作 And 组合；闭区间、最近前后观测和来源／掩膜参考 | <=1000 景；inner 最多 1000 匹配对，保留真实 Image 属性；请求度量时多重度量或 Or／Not 包含度量拒绝；空间／矢量、原生 E/G 未覆盖 |
| 静态 Array | S/C 与闭式独立 N；OLS 残差正交性、逆及秩一伪逆；工作预算拒绝 | <=8 轴／10000 单元、整数精确域 <=2^53；显式 PixelType／空构造／负下标拒绝；矩阵限二维，Solve 限满列秩方阵或超定；不含栅格 E/G |
| 固定形状栅格数组 | S/C；Image.toArray、arrayFlatten／Project／Transpose／Slice／Get／Length(s)／Reduce 和 matrixMultiply，同形 add／subtract／multiply／divide；独立合成图 N 验证来源、分量、重建及整体掩膜 | 单数组波段，<=8 轴／每轴 64／共 64 单元，非空维，共享 50000 工作步和 500 图节点；静态坐标、有限归约；Float32 callback 限制保留，动态形状／广播／直接数组栅格导出拒绝；无 E/G |
| 内联 FeatureCollection | S/C；size／first／toList／map／filter／limit／sort／merge／iterate／aggregate_array，属性保留有限 Array 和具体 Image；同类 Image 回调可接 ImageCollection 计算 | <=1000 要素，共享工作预算；Feature／Image 混合回调拒绝；merge 需要显式 ID 并加 1_／2_ 前缀；不含远程要素集或矢量引擎 |
| 静态行回归 | S/C 与独立 N；表格 reduceColumns／List.reduce 的 linearFit、linearRegression，多响应系数／RMS；缺失／null 行跳过；秩不足／n<=numX 返回 null | <=1000 行、<=32 个输入列，表格只支持平面属性选择器，List 要求精确行宽；共享预算、无权重；通用栅格 linearRegression 与 G 未覆盖 |
| 栅格 linearFit | S/C；完整 x/y 行、中心化两遍 OLS，输出 scale／offset；独立闭式与 NumPy SVD N 核对系数、重复景权重、缺测、空间范围及目标日期预测 | 1..8 帧，恰两个同名同序标量波段；binary NoData 掩膜，n<2／x 方差为零则两个输出均掩膜；parallelScale 仅 1，仍受 Float32 callback／工作／图预算约束；无实际 E/G，非通用栅格 linearRegression |
| 有限分类评估 | S/C 与独立标签频数 N；静态 ConfusionMatrix 构造、array／order／accuracy／kappa 与有限逐类指标；内联 errorMatrix 保留 actual 行／predicted 列及显式顺序 | <=64 类／4096 单元，非负整数 Array 计数总和 <=2^53、<=1000 完整标签行，共享预算；原始 List／浮点计数 Array、缺失／null、未定义分母、直接对象 JSON、Feature 属性对象拒绝；逐类指标返回本地 rank1 Float64，Fβ 采用实际行 recall 的明确推断，无 Google 形状／数值对照 |
| 有限 List 布局／归约 | S/C 与独立静态 N；zip／unzip 截短、flatten 只展开 List、repeat／reverse／set／swap 保留 typed 原子；单输出值、多输出回归字典／typed Array | 布局 <=10000 顶层值、flatten 深度 96，reduce <=1000 行／32 回归列，共享预算；严格下标边界，组合归约见上表，权重仍拒绝；空值政策见下文，无 E/G |
| 静态最小距离分类 | S/C 与独立 N；欧式／曼哈顿／cosine 光谱角、真实类均值、FeatureCollection.classify、schema 和训练重代入矩阵 | k=1／CLASSIFICATION、训练 1..1000 行、显式 1..8 平面属性、类别 0..63、subsampling=1／seed=0，共享预算；精确 binary64 有理数排名，等距、属性碰撞和 cosine 零范数查询／类中心拒绝；Mahalanobis、采样、图像分类及 G 未覆盖 |
| 有限栅格 linearRegression | S/C 与独立样点／SVD N；过原点或单位截距模型，多响应共用完整行，真实系数 (numX,numY) 与 RMS (numY,) | numX=1，或 numX=2 且首列证明为单位字面量；numY=1..4、1..8 同序标量帧，n>numX／非退化，RMS 按 n；parallelScale=1、Float32 callback、工作／500 节点限制，无通用设计矩阵／E/G |
| Number／String | S/C；%s／%d／%f、有限符号及填充；数值 String 构造与三个基础方法；指数拼接预算负控 | Number 按 Python 最短十进制拼写半入舍入，String 按 Python code point；科学／十六进制格式等拒绝；本地政策无 G |

List.contains／distinct 对嵌套数组使用显式的有界比较，避免 NumPy 隐式真值／广播错误。标量 int／float 按数值比较，bool 单独区分；Array 的 dtype／形状／元素比较仍是未做 Google 对照的本地策略。step 序列严格检查实际生成的 Float64 值，不向端点外扩展；例如 0、0.1、0.2 后的 0.30000000000000004 超过 end=0.3，因此省略，该舍入策略尚无 G 证据。

另有 65 项 Python／JS 固定 SDK 实际序列化后进入共享编译器的结果一致性回归，覆盖 count 序列、Dictionary、矩阵、notNull、Join（含 inner 和复合时间条件）、几何、表格回归、要素遍历、格式化及字符串构造；包括静态数组布局／归约、特征分解、Cholesky、QR／LU／SVD 和逐元素算术，以及栅格数组投影／归约、逐像元 linearFit 计算图、混淆矩阵 Kappa、标签误差矩阵、列表布局／均值／回归、最小距离 schema／预测／训练误差矩阵、栅格 linearRegression 的过原点／截距系数与 RMS、方阵／高矩形设计的栅格 matrixSolve、集合定长数组、reshape、正余弦设计，以及静态向量范数／方向角、栅格 hypot、轴拼接／整块重复与矩阵对角／迹／行列式、前缀归约／缩放范数和单数组选择，新增首个最大值坐标与 typed 空切片。这是保留共享后端行为的检查，不表示已完成 JavaScript 全量兼容或 Google 数值对照。

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

原始嵌套 List 虽可被 SDK 序列化，本地构造仍要求 typed Array；浮点计数 dtype、显式 Array PixelType 和直接／嵌套矩阵对象 JSON 仍拒绝。内部矩阵可经 If／Dictionary.get 再调用方法，但尚不能存入 Feature 属性。该批仅实现 array／order／accuracy／kappa；第二十批补上有限逐类指标，具体形状政策与限制见后文。原批次的独立 Luna max 复审未发现声明子集内可复现缺陷；S/C/静态 N 通过，网络入口尝试 0，不涉及栅格 E、G 或采样／分类器训练预测。

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

原第九批 minimumDistance 仅 Euclidean；第二十一批补上 Manhattan 与 cosine 光谱角分类，仍为 kNearest=1、CLASSIFICATION；显式唯一平面 schema 1..8，完整有限数值要素 1..1000，类别为 0..63 整数，subsampling=1／seed=0。几何按官方训练描述忽略；预测按名称读取属性，不依赖字典顺序。精确 Fraction 保留 binary64 输入并计算类均值：欧式比较平方距离，曼哈顿比较绝对差之和，cosine 比较带符号归一化点积的精确交叉乘积，不先用 Float64 求范数或 acos。任何等距最近类明确拒绝；cosine 的零范数查询或类中心在预测时拒绝，构造／训练／schema 不提前伪造预测结果。这一本地数值政策不等于已验证 Google／Smile 的浮点累加策略。共享工作上限仍生效，1000×8 的组合可能因预算拒绝。

模型不可变，If／Dictionary.get 再包装后可用；未训练 schema 为 null。要素分类保留属性／几何／ID、拒绝输出名碰撞，训练混淆矩阵用真实重代入预测、轴为 0..max 类别并保留空档。直接／嵌套模型 JSON、模型真值、Mahalanobis、kNearest≠1、REGRESSION／RAW／概率模式和自动 band_order schema／随机子采样仍拒绝。Image.classify 的第二十三批子集见文末；没有采样、完整栅格 E、随机森林或 G 的实现声明。

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
| `neighborhood_reduce_kernel` | passed | passed | 五波段均值；原生／Google证据另记 |
| `focal_mean` | passed | passed | 五波段像素单位圆核；原生／Google证据另记 |
| `join_save_first` | passed | passed | blue, green, red, nir, SCL |
| `array_matrix_multiply` | passed | passed | [[3],[7]] |
| `regression_reducer` | passed | rejected | ImageCollection.reduce linearRegression requires exactly 3 scalar bands per frame；原探针实际使用 5 bands，属于输入数量不匹配 |
| `classifier_constructor` | passed | rejected | Unsupported internal value at the public JSON boundary；分类器构造值需接入 train／classify，不能单独作为公开 JSON 结果 |
| `export_image_drive` | passed | passed | NIR |
| `export_table_drive` | passed | passed | {"features":[{"geometry":{"coordinates":[[[100.1,30.1],[100.9,30.1],[100.9,30.9],[100.1,30.9],[100.1,30.1]]],"type":"Polygon"},"properties":{"mean":3,"scene"... |

## 第十六批：轴拼接、整块重复与双响应数组求解

Image.arrayCat 必须提供 image1／image2／axis，只接受 rank 1..8 的单个固定数组，非拼接轴长度相同。输出保留真实行主序单元和 dtype，合取两个输入的整体掩膜，沿用左名称／属性和既有来源回退政策；不做标量广播或多数组波段配对。

Image.arrayRepeat 必须提供 input／axis／copies。固定签名中 copies 是 Image，Python wrapper 的 Any 注解不改变该签名。本地子集要求其为单标量波段的有效纯常量正整数，真实执行常量表达式及每层 Float32／Double 转换；有源、映射、footprint、掩膜、动态值、零／负值及非整数均拒绝。重复整个轴块，例如 `[1,2]` 重复两次得到 `[1,2,1,2]`。两项操作均限定已有非负轴，保留 rank≤8、每轴／总单元≤64、共享 50000 工作步和 500 图节点预算，输出构造前收费。这些限制是本地支持子集，不是 Google 服务的完整参数限制。

`examples/21_GEE_python_multi_response_arrays.py` 与 `tests/fixtures/ee-multi-response-arrays-v1.json` 将四景按实际时间排序，用 arrayRepeat 构造截距列、arrayCat 拼入自变量及两个独立响应列，再经显式 Float32 matrixSolve 求解。设计矩阵为 `[[1,0],[1,1],[1,2],[1,3]]`，正规矩阵为 `[[4,6],[6,14]]`。第一样点两响应截距／斜率分别为 `(2,3)` 和 `(-1,1/2)`；含噪声样点为 `(1,2)` 和 `(-2,1/2)`，两响应残差分别为 `[1,-1,-1,1]` 与 `[2,-2,-2,2]`。

系数、拟合、残差独立编译为 208／284／328 节点，Fraction 闭式和独立 NumPy SVD 按 2e-6 容差核对。任一响应任一帧缺失会掩膜两个响应的全部结果，不进行完整行删除；保留实际帧顺序、负／零值和 bbox 内但非矩形场景外的掩膜控制。SDK 网络入口尝试为 0。S/C/采样点 N 与未运行的栅格 E／Google G 分开登记，见 [第十六批报告](../../reports/gee-python-wave16.json)。

## 第十七批：矩阵描述量与样本协方差

四个新方法均要求唯一必填参数 value，未知／缺失参数明确拒绝。matrixDiagonal 只接受固定 rank2 数组，将矩形对角线返回为 `min(rows,columns)×1` 列，引用真实单元并保留原有转换。matrixToDiag 要求显式 Float32 单列、1..8 行，构造 `n×n` 矩阵，原单元在对角线上，非对角线为真实 Float32 零。matrixTrace 限显式 Float32 方阵 1..8，matrixDeterminant 限方阵 1..4；均输出保留数组名称的标量 Image，沿用原元数据、来源和完整输入掩膜，包括非对角线缺失。

迹的每次相加、行列式每次乘法及有符号累加都显式转 Float32，使常量折叠与栅格回调按相同阶段舍入。行列式采用有界排列多项式，奇异输入可返回零；该算法不是稳定选主元 LU，不声称消除抵消或溢出，也没有 Google 同数据对照。矩形 trace、动态／多数组波段、未显式 Float32 的算术和超出尺寸均拒绝，结构性对角提取保留单元转换不代表通用 Float64 算术已支持。共享 50000 工作、64 单元和 500 图节点限制保留，输出构造前收费，部分 4×4 栅格图仍会因节点数拒绝。

`examples/22_GEE_python_synthetic_covariance.py` 与 `tests/fixtures/ee-covariance-descriptors-v1.json` 从四景实际 red／nir 样本构造 `4×2` 数组，静态中心化矩阵 H 左乘后计算 `XᵀX/(4-1)`，并输出协方差、迹、行列式、对角列及对角矩阵。第一样点协方差为 `[[5/3,2/3],[2/3,4/3]]`，迹为 3、行列式为 16/9；第二样点协方差为 `[[5/3,-5/3],[-5/3,5/3]]`，行列式为零；第三样点 red 方差为零、nir 方差为 2/3。Fraction 手算与独立 NumPy `cov(ddof=1)` 验证矩阵及半正定性，实际图采样按 2e-6 核对。

真实编译图节点数为中心化 266、协方差 370、迹 310、行列式 374、对角列 308、对角矩阵 313。任一景任一波段缺失会掩膜该像元全部输出，不做行删除；顺序、负／零值和 bbox 内但多边形外样点均有控制。SDK 网络入口尝试为 0；本例是显式构造的有限样本协方差，未注册 Reducer.centeredCovariance 或声称完整采样器兼容。S/C/采样点 N 与未运行的栅格 E／Google G 见 [第十七批报告](../../reports/gee-python-wave17.json)。

## 第十八批：前缀归约与累计异常

Image.arrayAccum 必填 input／axis，reducer 省略或 null 时为 sum，显式 sum／min／max 计算包含当前位置的前缀；其他 reducer、unweighted 修饰符明确拒绝。输入为显式 Float32 的单个固定数组，rank 1..8，axis 为已有非负整数，行主序和数组形状不变，每个更新阶段转 Float32。保留完整输入掩膜，不通过删除缺测或只检查当前前缀制造有效像元；64 单元、50000 工作及 500 图节点预算保持。

Image.matrixFnorm 必填 value，输入限显式 Float32 的固定 rank2 数组。实际计算 `scale=max(abs(x))`，再求 `scale*sqrt(sum((x/scale)^2))`，沿用零分母返回零的已有合同，使全零矩阵得到零。各算术阶段显式 Float32；既有名称／属性／来源和整体掩膜保留，未新增后端进程。3e30／4e30 与 3e-30／4e-30 分别得到约 5e30／5e-30，以 Decimal 平方和开方、rtol=3e-6／atol=0 验证；最后乘回 scale 仍可能超 Float32 范围，已知常量溢出与动态溢出分别登记，不能宣称所有有限输入都有有限输出。

单数组 Image.select 复用多数组选择规则，支持原始逻辑名称或下标 0、可选单个 newNames，保留实际单元／转换／掩膜／元数据；空、重复、正则选择器或不匹配的新名称仍拒绝。真实工作流触发的单波段 `toArrayPerBand().select('ndvi')` 原先被拒绝，本批实际补上该类型重载，保留原调用作为回归。

`examples/23_GEE_python_cumulative_anomaly.py` 与 `tests/fixtures/ee-cumulative-anomaly-v1.json` 对 2024-01-01 至 2025-01-01 的四次合成 NDVI 观测减去明确的逐景参考基准 0.25。实际日期相差 366 天，day180 的两个不同 ID 均保留。第一像元异常为 `[-1/20,3/20,-7/20,1/20]`，累计和 `[-1/20,1/10,-1/4,-1/5]`，平方范数 3/20；另一个像元平方范数为 3/8，全零像元为零。Fraction 前缀、Decimal 开方及独立 NumPy 参考核对负／零、同日身份、排序和跨年日期。任一景缺失及 bbox 内多边形外样点均使整体结果无效。

异常图为 88 节点，默认／显式累计和、前缀 min／max 各 110 节点，范数 176 节点。SDK 网络入口尝试 0；这是真实数组表达式计算，样本和基准为明确版本化合成值，无栅格 E／Google G 结论，见 [第十八批报告](../../reports/gee-python-wave18.json)。

## 第十九批：最大值坐标与光谱原型选择

Array.argmax 严格要求唯一必填 array，保留 typed Array 的数值类型，直接按行主序扫描，仅在严格更大时更新，因此并列取第一个。返回每轴整数坐标列表，rank0 为 []，已有 typed 空切片为 null；直接空构造、显式 PixelType、非有限值和整数超出既有 ±2^53 精确域仍拒绝。rank≤8、10000 单元、共享 50000 工作预算不变，扫描及结果构造前预充 `2*cells+rank+1`。

Image.arrayArgmax 的固定参数名为 image，接受每个单元统一显式顶层 toFloat 或 toDouble 的单个固定 rank1..8 数组，按声明精度比较并求首个最大值的坐标，输出 shape(rank,)。坐标为 0..63 内的整数值 Float32，未证明 Google Integer dtype 等价；嵌套 Float32 转换仍可能形成新并列。rank0 所需空向量、未转换／混合顶层类型、标量及多数组波段明确拒绝。

全部输出保留原名称／Image 元数据／来源和完整输入掩膜，非赢家单元的缺测也使全部坐标无效，不局部删除缺测。构造前按 `cells*(2*rank+4)+rank²+2*rank+metadata_work` 预充，64 单元和 500 图节点保持；大动态图即使维度合法仍可能拒绝。

`examples/24_GEE_python_spectral_prototypes.py` 与 `tests/fixtures/ee-spectral-prototypes-v1.json` 对实际合成 red／nir 像素和明确的三个原型逐项计算差、平方和、负分数及 argmax。前五个有效像元选择 `[0,1,2,0,0]`；第四像元距离 `[1/32,1/32,5/32]` 按首个并列选择，第五像元所有分数为负，精确匹配的零分数仍有效。Fraction／Decimal 与独立 NumPy 参考、单波段缺测和 bbox 内多边形外控制分别验证。距离／分数／索引图实际为 113／125／136 节点，SDK 网络入口尝试 0。

这是固定原型的真实光谱选择表达式，未注册 Image.classify 或替代分类训练。S／C／采样点 N 与未运行的栅格 E／Google G 分别见 [第十九批报告](../../reports/gee-python-wave19.json)。

## 第二十批：按键排序、质量筛选与逐类指标

Array.sort 与 Image.arraySort 接受可选 keys，省略或 null 时使用值本身。keys 与值 rank 相同，恰有一个非单例轴，其长度与值的相应轴一致，其余键维度为 1；按升序置换整个切片，不能把各列独立排序。并列键保持输入顺序是本地明确政策，无 Google 对照。静态 typed Array 保留 dtype，支持可唯一确定排序轴的空切片；单单元／rank0 identity 也是本地政策。静态矩阵默认键具有多个非单例轴时明确拒绝。

栅格排序只接受 rank1..8 的固定单数组，值与键分别要求内部统一显式 toFloat 或 toDouble，两者精度可以不同。严格 gt 的相邻比较交换构造实际条件表达式，所有键和所有值的有效性共同约束输出；保留输入名称、元数据、来源回退与行主序。Float32 量化可能产生新并列，缺失的非赢家输入也不会变成有效值。64 单元、50000 工作与 500 图节点限制保持，构造前收费；16 个动态单元排序的超图预算有拒绝回归。Double 条件载荷通过有界原生选择保持精度；标量、多数组波段、未转换／混合顶层类型及含糊键形状不自动转换。

`examples/25_GEE_python_quality_sorted_observations.py` 和 `tests/fixtures/ee-quality-sorted-observations-v1.json` 对四景合成 red／nir 计算 NDVI，将 NDVI／距起点天数成对排序，再选质量最好的两次观测求均值。时间跨度含闰年 366 天和两个同日不同 ID；第一像元的顺序为 b、c、d、a，最佳两次均值为 7/12，全部键并列的第二像元均值为 1/4。缺失键、缺失反射率及 bbox 内多边形外像元都保持整体无效。独立 Fraction 行排序与实际编译图采样按 2e-6 核对；三个输出的图规模和误差记录在报告，无真实栅格 E／Google G 结论。

ConfusionMatrix.consumersAccuracy 按固定描述取对角／行和，producersAccuracy 取对角／列和；注意官方名称与实际行／预测列的统计惯例并不一致。Fβ 采用实际行 recall、预测列 precision 的显式推断，使用精确 Fraction 中间量避免巨大／次正规正 beta 平方溢出或下溢。结果是本地 rank1 Float64 向量；官方页仅声明 Array 返回，没有足够证据证明其 rank／dtype 与 Google 相同。零分母、非有限／非正 beta 及未知参数明确拒绝，原有计数、类别和工作预算不变。训练重代入和独立验证表的 errorMatrix 组合均有回归。

## 复现与后续顺序

```sh
.venv/bin/python -m scripts.ee_python_inventory
.venv/bin/python -m scripts.ee_python_probes --check
.venv/bin/python -m pytest -q
npm --prefix web test
.venv/bin/python scripts/build_web.py
```

继续按真实 Python 项目依赖补全栅格数组、逐像元回归，然后采样／分类训练预测、矢量／空间 Join、邻域／高级时序；优先使用版本化合成样本验证计算语义，本阶段不推进 Linux 隔离适配或要求原生／真实数据验收。固定原50探针现有47项编译通过、3项定向拒绝：全局footprint的unmask、原回归探针输入数量错误，以及把未训练smileRandomForest构造器直接作为公开JSON结果。这不表示实际RF训练未实现，也不是剩余功能的完整清单。

[GOAL.md](../../GOAL.md) 记录持续目标；[云端交接](../cloud-handoff.md) 保留环境和发布约束。Python 达标后再系统推进 JS，期间共享后端改动持续回归已有 JS 功能。

## 第二十一批：最小距离度量与独立分类验证

`examples/26_GEE_python_distance_metric_validation.py` 与 `ee-distance-metric-validation-v1.json` 使用显式 `[nir,red]` schema，从四条训练行求类中心 `(3,0)`、`(2,2)`，对六条独立验证行预测。欧式预测 `[1,1,0,0,0,1]`，验证矩阵 `[[1,1],[2,2]]`、准确率 1/2；曼哈顿预测 `[0,1,1,0,0,1]`，矩阵 `[[2,0],[1,3]]`、准确率 5/6；cosine 预测 `[1,1,1,0,0,1]`，矩阵 `[[1,1],[1,3]]`、准确率 2/3。训练矩阵三者均为 `[[2,0],[0,2]]`，不能用训练准确率代替验证表现。

参考分别采用独立 NumPy 距离、Decimal 归一化点积和 Fraction 频数／指标；另以 1600 位 Decimal 的显式归一化与开方检查负方向、极大／次正规值、相近方向及正比例缩放。生产比较器不执行浮点范数或 acos，保留符号后比较精确平方交叉乘积。精确有理数及零范数／等距拒绝是本地政策，未经 Google／Smile 等价验证。工作预算在候选评分前预收，欧式原成本保留，曼哈顿与光谱角额外收费；未增加任何上限。

测试验证了所选 metric 从构造到训练／预测不丢失，保留输入顺序、属性、几何及 ID，并将结果继续送入 errorMatrix、accuracy、consumersAccuracy、producersAccuracy 和 Fβ。官方 Python／JS SDK 一致性回归增至 65 项。可信进程内 SDK 测试的 OfflineGuard 记录网络入口尝试 0，这不等于内核隔离或运行流量抓包。

本批 1583 passed／3 skipped，较第二十批增加 48 项通过；前端 11 项、TypeScript／临时目录构建通过。原 50 项探针仍为 45 编译／5 拒绝，完整固定 Python API 清单独立生成字节相同。证据为 S／C／独立静态 N，无栅格 E／Google G；未部署到运行服务。Mahalanobis、k>1、REGRESSION／RAW／概率、随机采样、自动 schema、Image.classify 仍未支持；内联分类要素的 CSV 任务导出也未接通，现有区域 CSV 合同不能代替这一能力。详见 [报告](../../reports/gee-python-wave21.json)。

## 第二十二批：分类要素 CSV 批任务导出

内联 FeatureCollection 的 Export.table.toDrive 现能从真实编译结果创建本地批任务，经 worker.prepare、既有受限批任务入口的 CSV 分支、worker.finish／最终化器和统一结果解析器完成文件生成、选列、命名、发布及读取。图严格限定为 local_ee_table 字面输入直连 save_result(CSV)，不初始化 Spark/JVM；同名 process_id／from_node／process_graph 属性保持数据，目录快照和物化不扫描它们。原有区域 CSV 与栅格分支保留，未开发新的隔离适配器。

示例 27 实际串联三种最小距离度量、验证准确率与三个导出任务，每份 CSV 含六行，预测与上一批独立参考一致。Python 官方 Task 路径、JS runner 的对象／位置参数 wrapper、选择器列表／逗号字符串均有实际 CSV 内容检查；训练、任务状态、列表、取消、幂等重试、兄弟脚本及其他用户拒绝也有回归。这里数据库／队列和传输／进程启动由测试替身接管，不表示实际 PostgreSQL、HTTP、Seatbelt 或浏览器已运行。可信 SDK 与 JS 网络入口守卫为 0，不能等同流量抓包。

默认 system:index、首次出现的属性、.geo 列及 null／嵌套 JSON 单元均采用明确[本地序列化政策](numerical-policies.md)。支持的几何限二维平面 WGS84；其他 CRS、geodesic=true、evenOdd=false 和 west>east 的跨反经线 bbox 明确拒绝，bbox 需包住该层实际几何，属性中同名字段仍是普通数据。1000 行／256 列／50000 默认单元及 UTF-8 输入输出各 1 MB 上限，与既有转义后 EE 表达式／进程图 1 MB 限制共同生效。

复核发现并修复了 CRS 被忽略、bbox 未检查包含性、CSV 内部 CRLF 被归一化、大文本字段超过 Python 默认解析限制，以及 macOS 临时根别名被错误拒绝；对应边界均有回归。根别名校验仍由共享物理解析器拒绝 jobs／job／out 子符号链接，目标文件用独占且不跟随链接的方式创建。最终可移植 Python 1685／3，较上一批增加 102 项通过；前端 11、TypeScript／构建通过。原 50 探针和完整 Python API 目录不变，65 项 Python／JS SDK 结果一致性继续通过。报告区分 S／C、独立静态 N、实际 CSV 夹具执行与未运行的栅格 E／Google G；GeoJSON／SHP 等其他表格格式、云端目的地、采样／Image.classify、完整原生和生产验收仍未完成。

## 第二十三批：精确模型的影像分类

`Image.classify(image,classifier,outputName="classification")` 接受现有已训练的 minimumDistance 子集（Euclidean／Manhattan／cosine，k=1／CLASSIFICATION）。按训练 schema 名称读取 1..8 个标量波段并明确排列，额外波段的掩膜不参与；缺少／重复名称、非影像／数组输入、非法输出名和未绑定的纯常量栅格拒绝。单输出替换为分类波段，沿用属性、时间、网格和有限来源／足迹；map／rebind、rename、addBands、地图及未提交的导出表达式有回归。

精确类中心通过五字段 version-1 wire（version／metric／schema／labels／centers）传输。中心为已约分的十进制分子／正分母字符串；每项最多 700 字符、2200 bits，绝对值不超过最大有限 binary64。零只编码为 0/1，标签为 0..63 的有序唯一整数。API 图校验、受信任 Python 桥和 Scala 解析均检查模型；共享 50000 工作／500 图节点及原有网格、key、decoded-cell 限制保留，原生分类另限制 pixel×class×band≤67108864。

专用 `local_ee_minimum_distance` 接收按 schema 排列的 cube，Double 按 IEEE 位恢复精确分数，不经过通用 Float32 callback；已由其他运算量化的输入不会恢复丢失精度。欧式可约去共同查询平方范数，比较 `2q·c−c·c`；曼哈顿求绝对差和，cosine 使用带符号交叉乘积比较归一化点积。输出物理类型为 Int32 NoData，单波段先名为 v，再恢复 SDK 输出名。任一所选 NoData 掩膜输出；有效 Infinity、最近类精确并列、cosine 零查询明确拒绝，cosine 零类中心在生成预测模型时拒绝。上述 ties／dtype／精确累积均属明确本地政策，没有 G 对照。

示例 28 与 `ee-raster-classification-v1.json` 使用两景／三个类中心 `(3,0)`、`(2,2)`、`(1/3,1/2)`，覆盖 schema／源波段顺序不同、aux 缺测不污染、必须波段缺测及 bbox 内多边形外样点。三种度量各 12 个采样位置用 Fraction 距离／Decimal 开方归一化参考核对，真实官方 Python／JS 序列化图一致性新增 3 项（总 68）。

可信 standalone JVM 内核另有 141 项预测／掩膜／错误控制、16 项非法模型及 9 项 binary64 精确解码；含固定随机、最大有限／次正规数、混合极值、1/3、负方向、0／63 标签与等距拒绝，实际调用 GeoTrellis tile 内核。启用 `LOCAL_EE_RUN_CLASSIFIER_KERNEL_TEST=1` 后全套 1751 passed／3 skipped，较第二十二批增加 66 项；未启用时新增内核测试会单独跳过。完整 Spark cube、运行器／Seatbelt、HTTP／浏览器／部署及 Google G 均未运行；这项组件验证不能替代这些验收。采样、随机森林、Mahalanobis、k>1 和其他模式仍待实现。[报告](../../reports/gee-python-wave23.json)。
