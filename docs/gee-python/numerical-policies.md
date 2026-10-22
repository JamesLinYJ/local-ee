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
