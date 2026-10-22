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
