# GEE Python／JavaScript 兼容范围

基线：官方 `@google/earthengine` 1.7.49，仓库提交 `e189e4b89e785019ea5642ea8e80cb644749cd4a`。客户端构造和序列化逻辑直接复用官方构建；签名文件也固定到同一提交，见 `vendor/earthengine-js/upstream-lock.json`。

Python 编辑器同时提供官方 `earthengine-api` 客户端入口，版本 1.7.49 固定在同一上游提交的 Python 子目录；许可证、源码树及关键文件摘要见 [`vendor/earthengine-python/upstream-lock.json`](../vendor/earthengine-python/upstream-lock.json)。Python 和 JavaScript 会生成相同格式的 EE 表达式并进入同一个本地兼容层；二者都不连接 Google 计算服务。客户端语言和官方 SDK 覆盖面不表示本地编译器已支持所有调用。

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
| Algorithms.If | 静态条件，惰性编译选中分支 | S/C；不把影像对象当作静态布尔条件 |
| 几何与地图 | 平面 WGS84 Geometry；Image/Collection/Feature.geometry；Map.centerObject、setCenter、addLayer | S/C；真实地图和 RGB 预览 N |
| 影像导出 | toDrive 适配本地 GeoTIFF/NetCDF；region 精确掩膜、scale/crs、fileNamePrefix | 真实三角形区域 N；网页文件名回读 |
| 区域统计与表格 | reduceRegion、单 FeatureCollection 包装导出 CSV、selectors 选择/排序输出波段 | 单景区域均值 N；不支持任意静态表格导出 |
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
- 分类器、栅格回归和 Image.array* 运算、超出上述有限元数据范围的 join、邻域卷积、ui.Chart/ui.Panel 等完整 GEE 应用组件。静态 Array.matrixSolve 的独立线性代数验证不能代替逐像元时序回归。
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
| 谐波时序与矩阵回归 | 已补有限逐景日期 map、日期常量 band、受限日期与静态 Array.matrixSolve；仍缺栅格 `linearRegression/linearFit`、Image.array*，以及相位/振幅的 `atan2/hypot` |
| HISTARFM 插值 | 已补受限 Date.getRelative、saveAll 匹配影像列表、maxDifference 与方向比较的 And 组合；最近前后观测像素插值有合成图 N，独立常量栅格、int16、完整项目及真实引擎验收仍缺失 |
| 随机森林与验证 | 样本提取、分类器训练/预测、混淆矩阵与批量区域统计 |
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
