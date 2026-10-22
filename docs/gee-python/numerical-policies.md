# 数值政策与尚未确认的行为

更新：2026-10-22。这里记录固定 SDK 合同、本地算法和 Google 服务实测之间的区别；已有独立数值结果不等于 Google 同数据对照。

## atan2 的参数轴

`earthengine-api` 1.7.49 固定到上游提交 `e189e4b89e785019ea5642ea8e80cb644749cd4a`。[Array.atan2 的固定源码](https://github.com/google/earthengine-api/blob/e189e4b89e785019ea5642ea8e80cb644749cd4a/python/ee/ee_array.py) 明确将 `right` 记为 y；Number 的描述是向量 `[x,y]`。本地静态 Number／Array 采用 x=实例／left、y=right，因此调用数学库的 `atan2(right,left)`。这是明确采用的 SDK 合同解释，Google 服务的实际轴顺序尚未用相同输入核对。

官方社区[谐波教程的固定版本](https://github.com/google/earthengine-community/blob/9bf837941bcac693c958b3bad55b4516ea7d406a/tutorials/time-series-modeling/index.md#L320-L435) 在推导中写 phase=atan(sin 系数／cos 系数)，却调用 `sin.atan2(cos)`。这个 2022 年示例反映了不同的调用约定；单靠它不能校准固定 SDK 所描述的方向。示例源文件 SHA256 为 `3cab806d520590e5401ba8f333666456afeb4f5667a2d100a7988f549b73e960`。

本地四象限、坐标轴、非对称向量及 signed-zero 分支均有独立级数／几何参考；这些只验证上述数学政策。缺参、未知参数、非有限／非数值和 bool 输入明确拒绝。Array 限同形 typed Array，不实现广播。

`Image.atan2` 继续拒绝。仓库固定的 GeoTrellis 扩展提交 `d240b43160bc65272c6c02f9501dced363525dc4` 的 [ScriptBuilder 源码](https://github.com/Open-EO/openeo-geotrellis-extensions/blob/d240b43160bc65272c6c02f9501dced363525dc4/openeo-geotrellis/src/main/scala/org/openeo/geotrellis/OpenEOProcessScriptBuilder.scala#L1183-L1203) 在第 1188 行仍把 `arctan2` 标为 TODO。JAR 摘要存在，但尚无 source commit 到该二进制的构建映射；不能据 Python 进程注册或 NumPy 实现推断 JVM callback 已支持它。没有新增 arctan2 进程白名单，也没有在栅格工作流中伪造相位。

## hypot 的精度与范围

Number.hypot 使用真实 Float64 libm 内核，Array.hypot 使用真实 NumPy Float64 内核；有限结果保持类型和形状，非有限结果拒绝。整数输入限精确域 <=2^53，Array 另受既有 rank／cells／work 预算限制。Decimal 高精度平方和开方与有理数勾股数提供独立参考。

Image.hypot 通过既有像素算子计算：`high=max(abs(x),abs(y))`、`low=min(abs(x),abs(y))`、`high*sqrt(1+(low/high)^2)`，除零沿用返回零并保留 NoData 的合同，最后显式转 Float32。比例形式避免直接对 3e30／4e30 或 3e-30／4e-30 平方造成的中间溢出／下溢，但逐步 Float32 舍入不等同于直接融合 hypot 的最后几位。显式 Float64 callback 输入仍拒绝，调用方可以明确选择 toFloat。

输出范围仍受 Float32 限制。两个有限且可表示的输入 3.3e38 的真实范数约为 4.67e38，超出 Float32：本地采样点求值产生正无穷；同样的直接常量输入因结果可预知而在编译时拒绝。该差异有实际 SDK 回归，不能将 Image.hypot 宣称为“所有输出均有限”。真实栅格引擎和 Google 对这类溢出的处理尚未验收。

波段配对、单波段广播、较长输入的名称、左属性和来源回退沿用既有 Image 合同；NoData 按各配对波段传播。预充工作和 500 节点限制保持。独立采样点参考、序列化和编译通过仍分别只属于 S／C／N，无 E／G 结论。

## 固定栅格矩阵描述量

Image.matrixDiagonal 只重排真实单元引用，保留完整数组掩膜和原有类型转换。Image.matrixToDiag 当前要求单列的每个单元显式 toFloat，非对角线写入真实 Float32 零。保留转换信息不表示通用 Float64 回调已经支持。

Image.matrixTrace 当前限 1..8 的显式 Float32 方阵，按行号逐步累加对角线；每次加法后及输出处都显式转 Float32。Image.matrixDeterminant 限 1..4 方阵，使用有界排列多项式，每个乘积和有符号累加阶段也显式转 Float32。这样常量折叠与栅格回调遵循相同的舍入阶段；一般稠密 4×4 栅格表达式仍会触发既有 500 节点拒绝。

这不是稳定选主元 LU，也不保证有限输入总得到有限且精确的结果。正式回归使用三阶对角线 `[1e8,1,-1e8]`：常量和栅格的迹在该政策下均为 0，精确参考为 1；1e8 同时落在 Float64 可以保留中间加 1 的范围，因此也实际区分了逐步 Float32 与仅最后转换。独立 Fraction／NumPy 对普通范围的矩阵及四景协方差提供数值控制，不能抹去抵消和溢出边界。奇异矩阵可以返回零，不能一律当作不支持或伪造为其他值。完整输入掩膜仍有效：即使只取迹／对角线，非对角线原始缺测也会掩膜输出。

实际采样控制中，两个有限且可表示的 Float32 对角元素 1e20 的二阶行列式在乘法阶段溢出为正无穷；相同字面常量矩阵在常量折叠的显式 Float32 转换时拒绝为 UnsupportedEEError。固定舍入阶段并不消除这项常量／动态错误处理差异。该行为有独立只读复核及回归控制，不是 Google 或原生引擎溢出政策的结论。

矩形 trace、未经显式 Float32 选择的算术、变长／多数组波段均不在当前子集中。上述形状和精度限制是本地实现政策，没有将其描述为 Google 服务的全部规则；E／G 仍未运行。

## 固定数组前缀与 Frobenius 范数

Image.arrayAccum 的 sum 按原轴顺序逐步 Float32 相加，包括当前位置；min／max 保留相同固定形状和完整输入掩膜。省略／null reducer 默认为 sum，未支持的 reducer 与修饰符拒绝。`[1e8,1,-1e8]` 的末项累计和在常量和动态路径均为 0，而精确值为 1；有限 Float32 的两个 2e38 相加可产生正无穷，字面常量转换溢出则在编译时拒绝。它不是精确有理数累积或已证明的 Google 舍入规则。

Image.matrixFnorm 采用最大绝对值缩放、比例平方和、开方后再乘回 scale，每个阶段显式 Float32，避开直接对原输入平方的中间溢出／下溢。零安全除法令全零矩阵范数为零，同时整体数组掩膜保留，不将缺测变成有效零。Decimal 参考对约 5e30 和 5e-30 的结果使用 rtol=3e-6、atol=0，能拒绝错误的小值归零；该稳定形式仍可能在最终输出超 Float32，动态结果与已知常量拒绝分别记录。形状／工作／图规模限制继续适用，无原生引擎或 Google 等价结论。

## 最大值坐标与显式量化

固定 SDK 的 Array.argmax／Image.arrayArgmax 都要求并列最大值取第一个。本地按行主序扫描，只在后一个值严格大于当前最大值时更新坐标；多维输出是每个轴的下标。静态 Array 保留原有数值类型直接比较，不先复制成 Float64，仍遵守既有有限值、整数精确域 ±2^53、rank≤8、10000 单元及共享工作预算。rank0 返回空坐标列表，已有 typed 空切片返回 null；直接空构造仍受 PixelType 限制。

Image.arrayArgmax 当前只接受 rank1..8、≤64 单元且每个单元显式顶层 toFloat 的单数组影像。比较在该显式 Float32 输入上执行：原来不同的 Double 值可能量化成相同值，再按首个最大值取坐标。这是用户选择 toFloat 后的本地子集行为，不是对 Google Double 比较的替代。输出为 shape(rank,) 的实际条件表达式，坐标在 0..63 内，以整数值 Float32 表示；尚未实现或证明 Google Integer 结果 dtype 等价。

整个输入数组的掩膜和来源／名称／元数据保留，即使缺测单元不会成为最大值，也掩膜全部坐标。rank0 栅格所需的空坐标向量不能由现有非空数组 IR 表示，因此明确拒绝；Double、标量和多数组波段不静默转换。扫描及构造前收费，50000 工作和 500 图节点预算保持。合成光谱原型选择用真实平方距离的负值求 argmax，是明确固定原型的计算流程，未实现 Image.classify 或完整分类训练。无栅格 E／Google G 结论。


## 按键排序与逐类指标

Array.sort／Image.arraySort 的可选 keys 按唯一非单例轴确定方向，保持整个切片的对应关系。并列键使用稳定升序的本地政策，未经过 Google 验证。静态数组保留原始 dtype；栅格值和键都要求显式 Float32，量化后不同 Double 可能成为并列。完整值／键掩膜共同作用，保留非赢家缺测，不删除观测。静态 rank0 单单元 identity 和 typed 空切片行为也是本地子集；栅格仍要求非空固定维度。工作收费在排序／DAG 分配前执行，图规模保持 500 节点。

ConfusionMatrix 的固定描述把 consumersAccuracy 定义为对角／行和，producersAccuracy 定义为对角／列和，尽管同一参考说明 actual 为行、predicted 为列。实现按固定方法描述计算，不暗中交换两个名字。Fβ 参考页只说 beta 加权 recall，故采用实际行 recall、预测列 precision 的明确推断：`(1+β²)TP/(β²·rowTotal+columnTotal)`。返回 rank1 Float64 是本地物化政策，官方 Array 返回声明不足以证明其与 Google rank／dtype 相同。相同数值不等于完整形状兼容。

beta 限有限正值，按其 binary64 精确有理数计算中间量，覆盖巨大和次正规 beta，不先用浮点平方制造溢出／下溢；不声称与 Google 最后位一致。零分母明确拒绝，不填零伪造指标。Fβ 两次矩阵遍历和结果分配均预收工作预算。第二十批报告分别保留独立分数参考、合成图采样、未运行栅格 E 与 Google G。

来源：[Array.sort](https://developers.google.com/earth-engine/apidocs/ee-array-sort)、[Image.arraySort](https://developers.google.com/earth-engine/apidocs/ee-image-arraysort)、[consumersAccuracy](https://developers.google.com/earth-engine/apidocs/ee-confusionmatrix-consumersaccuracy)、[producersAccuracy](https://developers.google.com/earth-engine/apidocs/ee-confusionmatrix-producersaccuracy)、[fscore](https://developers.google.com/earth-engine/apidocs/ee-confusionmatrix-fscore)。公式轴解释与输出 rank 属于上述明确推断／本地政策。

## 最小距离的曼哈顿与光谱角排名

Classifier.minimumDistance 的欧式、曼哈顿及 cosine 光谱角均围绕未归一化类均值计算。训练保留有限 binary64 输入的精确 Fraction 均值；欧式用距离平方排序，曼哈顿用绝对差之和。cosine 求最小光谱角等价于最大带符号归一化点积。查询范数对全部类别相同，比较时可约去；先比较点积符号，再对同号非零候选比较 dot² 与另一类范数平方的交叉乘积，负号情形反转比较方向。全过程不以 Float64 先求范数、平方或 acos，避免有限输入在中间步骤溢出／下溢或相近方向被舍入成同分。

这是精确输入下的本地分类排名政策，不返回实际距离值，也没有证明与 Google／Smile 的逐步浮点结果完全一致。零范数查询或任一类中心在预测时明确拒绝；训练／schema 本身不以预测代替校验。所有度量的最近类并列继续拒绝，不任取第一个。kNearest=1、CLASSIFICATION、显式 1..8 平面属性、完整训练行及共享预算继续适用，Mahalanobis／REGRESSION／RAW／概率模式没有用其他算法代替。

独立参考使用不同的 Decimal 归一化、除法和开方路径（极值控制 1600 位精度），覆盖负／零点积、最大有限值／最小次正规值、±2^53 附近的相近方向、正比例缩放与精确角度并列。中等范围的欧式／L1 另用 NumPy 距离核对；训练／验证混淆矩阵与每类指标使用独立 Fraction 频数参考。收费在候选循环和评分构造前执行，原欧式成本不变；不同度量因运算成本而可能在不同输入规模触发同一共享预算。

来源：[Classifier.minimumDistance](https://developers.google.com/earth-engine/apidocs/ee-classifier-minimumdistance)。本批为静态 S／C／N，没有采样、栅格 Image.classify、原生引擎 E 或 Google G。

## 内联表格的 CSV 序列化

官方 Export.table.toDrive 的 collection／selectors 被映射为本地持久批任务；toDrive 不向 Google Drive 传输数据。只接受已编译为静态 GeoJSON FeatureCollection 的值及 CSV，保留原有区域统计 CSV 分支；其他格式、云端目的地、maxVertices／priority 不以近似方式接收。表格在现有沙箱入口的受信任批任务代码中写出，图仅允许一个字面表输入直连 CSV sink，不能与栅格或回调混合。

默认列是 system:index、按首次出现顺序收集的其他属性、.geo。system:index 优先使用属性，否则使用 Feature.id；缺失为空。选择器为不重复的已知列，保持用户顺序；.geo 写紧凑 GeoJSON，null 几何为空，普通同名属性拒绝以免覆盖。字符串原文保留，包括逗号、引号、Unicode、回车和换行，使用标准 CSV 引号规则；缺失／null 为空，布尔为小写 true／false，有限数值使用 JSON 表示，数组和对象用紧凑 JSON。上述列序、缺失值及嵌套单元表示均为本地政策，没有 Google CSV 文件对照。

上限为 1000 行、含保留列的 256 列、行数×默认列数≤50000，紧凑 UTF-8 JSON 输入和 CSV 输出各≤1000000 字节、元数据容器深度≤32；选择少数列不会绕过全部输入校验或默认表格单元预算。既有 EE 表达式与进程图还有包含包装和 Unicode ASCII 转义的 1 MB 限制，故达到独立表值上限的输入未必能提交。几何只按明确的二维平面 WGS84 合同接受，不自动重投影或忽略不支持的坐标系／球面解释；bbox 与实际几何也独立校验；west>east 的跨反经线 bbox 明确拒绝，不宣称完整 RFC 7946 bbox 支持。

最终化器仍通过统一物理结果解析器处理文件；选列时用 newline='' 保留单元内部原换行，允许既有文件预算内超过默认 128 KiB 的字段，之后恢复进程 CSV 字段限制。编码或 CSV 解析错误作为发布失败处理，不让它们逸出调度循环。示例和集成使用临时文件实际验证内容，但数据库、队列和脚本传输有替身；没有据此宣称原生隔离、浏览器、栅格 E 或 Google G 已通过。

来源：[Export.table.toDrive](https://developers.google.com/earth-engine/apidocs/export-table-todrive)。本地目录／文件规则和预算不等于 Google Drive 的存储语义。

## 精确模型的影像分类与内核验证

第二十三批将同一 minimumDistance 精确类均值用于 Image.classify。模型中的 1/3 等分数不先取整为 Double；原生内核将实际 Float32／Float64 tile 样本读作 Double，并按 IEEE 位恢复精确值，再进行与静态模型一致的距离排名。此前 callback 已发生的 Float32 舍入不会被恢复。欧式通过约去共同 q·q 比较 2q·c−c·c，不计算可能溢出的浮点距离；曼哈顿为精确 L1，cosine 为带符号精确交叉比较。

所选任一波段 NaN／NoData 令输出缺测；额外未选波段不参与。有效 Infinity 即使与另一选中波段的 NoData 同处一像元也明确拒绝。最近类精确并列会令任务失败，不取首个、不伪造 NoData；cosine 零查询在预测时拒绝，零类中心在编译预测模型时拒绝。单输出物理类型 IntConstantNoDataCellType（Int32），0..63 为有效标签、Int.MinValue 为 NoData。它是本地输出合同，不表示已验证 Google dtype、tie 或逐步浮点算法。

API 和 Python 桥共用纯模型校验，Scala 另行独立解析。版本 1 仅五字段，Fraction 只接受规范有符号分子／正分母、约分、零0/1；每字符串≤700字符、≤2200 bits、中心有限 binary64 幅值。schema 为1..8个唯一平面名称，标签为1..64个排序唯一0..63整数。元数据顺序与实际输入 bandCount 均校验，原有网格／时间／key／cell 预算及新增67108864像元×类别×波段工作上限保持，不能通过直接提交 openEO 图绕过模型协议。

独立合成图 N 覆盖源范围、单景／映射多景及元数据。另一个 opt-in 测试真实编译并调用 GeoTrellis tile 内核，141预测控制的参考使用直接有理数平方距离／L1或1600位 Decimal 的归一化与开方路径，包含固定随机、极值、次正规值、负方向及掩膜；16非法模型同时核对 Python／Scala 拒绝，9个binary64值与Fraction.from_float核对。没有 SparkContext、完整 cube执行、NativeClient／Seatbelt任务、服务或浏览器，因此 E 的完整链路仍未验证；没有 Google 同数据对照。[Image.classify](https://developers.google.com/earth-engine/apidocs/ee-image-classify) 的按名称输入与默认输出名合同已核对，本地形状／边界政策单独登记。
