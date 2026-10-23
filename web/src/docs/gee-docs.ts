import type { ReferenceEntry } from "../types";
// Pinned client syntax and explicit local semantics; served entirely from this app.
const entries: ReferenceEntry[] = [
  {
    id: "gee-start",
    title: "GEE JavaScript 入门",
    text: "选择编辑器的 GEE JavaScript 模式。标准 JavaScript 由 macOS 原生沙箱中的 Node 进程执行；ee.* 使用固定的官方客户端构造延迟计算图，本地兼容层执行支持的算法。只有本地入库范围可计算；导出创建后在任务面板开始。",
    code: "var roi = ee.Geometry.Rectangle([113.55,22.30,113.57,22.32]);\nvar image = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')\n    .filterDate('2024-01-19','2024-01-20').filterBounds(roi).median();\nprint(image.bandNames());",
  },
  {
    id: "gee-js",
    title: "变量、函数与服务端对象",
    text: "支持 var/let/const、数组、对象、函数、箭头函数和普通 JavaScript 控制流。ee.Number 等是延迟对象：用 add/gt/ee.Algorithms.If 构造计算，不要用 JavaScript +、if 判断影像对象。map 回调构造一次计算图，不在浏览器逐像素执行。",
    code: "var threshold = 0.3;\nvar maskCloud = function(image) {\n    return image.updateMask(image.select('B4').gt(threshold * 10000));\n};",
  },
  {
    id: "gee-catalog",
    title: "数据别名、波段与单位",
    text: "COPERNICUS/S2_SR_HARMONIZED / COPERNICUS/S2_SR 指向已入库的 Sentinel-2 子集。B2/B3/B4/B8 映射 blue/green/red/nir，按反射率 × 10000 提供 DN 视图。本地数据已经用 SCL 去云，无法恢复被掩膜像素；QA60/B11 等缺失波段报错。使用本地 ID sentinel-2-l2a 则保留 blue/red/nir 等名称及反射率单位。此别名不代表全球 GEE 目录镜像。",
  },
  {
    id: "gee-filter",
    title: "日期、空间与属性筛选",
    text: "filterDate(start,end) 的结束时间不包含在内，支持毫秒边界。filterBounds(geometry) 选择足迹相交的影像，不裁剪像素；需要 clip(geometry) 才掩膜区域外像素。属性筛选只读取已有本地元数据，缺失字段不会伪造。",
    code: "var scenes = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')\n  .filterDate('2024-01-19','2024-01-20')\n  .filterBounds(roi)\n  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80));\nprint(scenes.size());",
  },
  {
    id: "gee-ndvi",
    title: "select / map / normalizedDifference",
    text: "select/rename 保留波段顺序；map 内用影像算子构造回调。normalizedDifference([a,b])=(a-b)/(a+b)，输出默认为 nd，负输入被掩膜；当前本地实现也掩膜零分母，该边界尚无原始 GEE 对照。属性不会自动继承。需要保留属性时用 copyProperties。expression 计算相同公式不会自动加负值掩膜。",
    code: "var ndvi = scenes.map(function(image) {\n  return image.normalizedDifference(['B8','B4']).rename('NDVI');\n}).median().clip(roi);",
  },
  {
    id: "gee-expression",
    title: "expression 与 updateMask",
    text: "expression 支持已实现的算术、比较、逻辑、部分数学函数及三元表达式，未知语法明确失败。updateMask 使用非零值保留有效像素，与 openEO mask 的方向相反；首版只接受二值掩膜，分数掩膜不支持。",
    code: "var ndvi = image.expression('(n-r)/(n+r)', {\n  n:image.select('B8'), r:image.select('B4')\n}).rename('NDVI');\nvar vegetation = ndvi.updateMask(ndvi.gt(0.3));",
  },
  {
    id: "gee-unmask",
    title: "unmask 缺测填充",
    text: "unmask() 用有效的 0 填充缺测；unmask(value) 接受数值或网格、时间维度一致的本地影像。有效的原值（包括 0）保留，替代影像自己的缺测继续缺测。默认保留输入 footprint，clip 外不会被填回。sameFootprint:false 只接受已对齐的有限栅格替代值，全局常量扩展报错。当前结果使用 Float64；有界逐景均值、中位数、计数等归约保留双精度，通用后续算术仍需显式 toFloat()，会降低精度。数值填充不会恢复真实观测。",
    code: "var image = scenes.first().select('B8').clip(roi);\nvar filled = image.unmask(32767);\nExport.image.toDrive({image:filled,description:'填充缺测',\n region:roi,scale:10,crs:'EPSG:32649',fileFormat:'GeoTIFF'});",
  },
  {
    id: "gee-composite",
    title: "median / mean / mosaic / qualityMosaic",
    text: "median/mean/min/max/sum/count 按逐景有效像素归约，同一天的影像不会提前合并。mosaic 从集合末尾向前选有效像素，保留显式排序；相同时间戳也按集合顺序处理。reduce(Reducer.mean()) 输出带 _mean 后缀的波段，toBands() 按 system:index 生成名称（本地最多 100 个输出波段，仍受 500 节点限制）。预处理、网格和重采样会影响结果。",
  },
  {
    id: "gee-quality",
    title: "qualityMosaic 按质量选景",
    text: "qualityMosaic('qualityBand') 在每个像素选择质量波段最大的影像，其他波段跟随同一景。质量缺测的景被排除；获胜景某波段缺测时保持缺测，不从其他景补值。当前要求各景波段名称与顺序一致；平分时按本地集合顺序取后景，该规则尚未与 Google 服务比较。仍受 500 图节点与本地景数预算限制。",
    code: "var scored = scenes.map(function(image) {\n  var ndvi = image.normalizedDifference(['B8','B4']).rename('NDVI');\n  return image.addBands(ndvi);\n});\nvar greenest = scored.qualityMosaic('NDVI');\nMap.addLayer(greenest.select('NDVI'), {min:0,max:1}, '最绿像素');",
  },
  {
    id: "gee-map",
    title: "Map.addLayer 与地图定位",
    text: "Map.addLayer 提交真实本地计算，任务完成后自动显示。支持单波段色带或三波段 RGB、min/max/gamma、shown 和 opacity。视图为本地网格，无外部卫星底图。改变色带只影响预览，不修改下载文件的数值。",
    code: "Map.centerObject(roi, 13);\nMap.addLayer(ndvi, {min:0,max:1,palette:['f5e7bc','a7c982','17663f']}, 'NDVI');\n// RGB：bands:['B4','B3','B2'], min:0, max:3000",
  },
  {
    id: "gee-export",
    title: "Export.image.toDrive → 本地文件",
    text: "toDrive 适配为本地导出，创建独立任务，不会上传 Google Drive。点击任务面板“开始导出”，或保存返回对象后调用 start()。region/scale/crs 参与计算，fileNamePrefix 决定实际文件名；支持 GeoTIFF、NetCDF。允许 maxPixels:1e13 等上限，但会按本地网格保守预检，并继续限制为最多 1 亿像素/波段及原生进程资源预算。暂不支持 toAsset/toCloudStorage、crsTransform、dimensions、分片等参数。",
    code: "var task = Export.image.toDrive({\n image:ndvi, description:'NDVI', fileFormat:'GeoTIFF',\n region:roi, scale:10, crs:'EPSG:32649'\n});\n// task.start();",
  },
  {
    id: "gee-region",
    title: "reduceRegion 与 CSV",
    text: "支持单幅影像的已实现区域归约和单 Feature 的表格导出包装。print/getInfo 遇到区域统计会有限等待一个真实任务，繁忙队列可能超时；大任务建议导出后在面板查看。不支持边界像元加权与任意 bestEffort/tileScale，自定义网格参数必须显式检查。",
    code: "var stats = ndvi.reduceRegion({reducer:ee.Reducer.mean(),geometry:roi,scale:10,crs:'EPSG:32649'});\nExport.table.toDrive({collection:ee.FeatureCollection([ee.Feature(null,stats)]),description:'区域统计',fileFormat:'CSV'});",
  },
  {
    id: "gee-dates",
    title: "Date 与 List 日期循环",
    text: "支持 UTC Date.fromYMD/get/millis/format、difference/getRelative/getFraction，以及整数月/年 advance。difference 的秒至周使用固定时长；年/月采用本地平均时长策略并输出未完成 GEE 对照的警告。周字段采用 ISO 周边界并提示限制；getRelative 的 week/month 与相同单位组合明确拒绝。其他时区、分数月/年和未知格式 token 明确拒绝。List.sequence/map/iterate/slice/distinct/sort 可用于日期和参数列表；map/iterate 每次最多 1000 项，生成列表最多 10000 项。Algorithms.If 只编译静态条件选中的分支。",
    code: "var dates = ee.List.sequence(0,2).map(function(m) {\n  return ee.Date.fromYMD(2024,1,31).advance(m,'month').format('yyyy-MM-dd');\n});\nprint(dates); // 2024-01-31、2024-02-29、2024-03-31",
  },
  {
    id: "gee-properties",
    title: "集合属性与逐景列表",
    text: "支持 aggregate_array、toList(count,offset)、Filter.inList、Filter.calendarRange（UTC，包含端点且可跨年）。原始集合 map 读取 image.date/get/propertyNames/geometry 时，自动逐景解析本地元数据，保留同一天的不同观测及集合顺序；set/copyProperties 与 map(...,true) 跳过 null 均可使用。纯像素 map 保留紧凑路径。逐景展开仍受 1000 景与 500 节点预算限制；支持 image.addBands(ee.Image(image.date().millis()).rename('millis'))，常量在目的影像的有限本地网格与 footprint 内有效，不继承源缺测；可 mean/count/sampleStdDev/toBands。独立全局常量与常量投影查询仍拒绝。",
    code: "print(scenes.aggregate_array('system:index'));\nvar first = ee.Image(scenes.toList(1).get(0));\nprint(first.date().format('yyyy-MM-dd'));\nMap.centerObject(first, 13);",
  },
  {
    id: "gee-fromimages",
    title: "fromImages / merge 与分期合成",
    text: "支持从 List.map 或显式影像列表构造集合、merge、逐景 map、筛选排序、属性数组、归约和 toBands。常用于按月循环，先判断 size()，用 Algorithms.If 返回影像或 null，再用 List.map(...,true) 跳过空月份。重复影像会保留计数。每个显式集合最多 1000 幅，仍受 500 图节点限制；纯常量集合的栅格网格尚未实现。",
    code: "var images = ee.List.sequence(0,2).map(function(m) {\n  var begin = ee.Date('2024-01-01').advance(m,'month');\n  var part = scenes.filterDate(begin,begin.advance(1,'month'));\n  return ee.Algorithms.If(part.size().gt(0),part.median()\n    .set('system:time_start',begin.millis()),null);\n},true);\nvar monthly = ee.ImageCollection.fromImages(images);\nMap.addLayer(monthly.mean(),{bands:['B4','B3','B2'],min:0,max:3000},'分期合成');",
  },
  {
    id: "gee-where",
    title: "where / clamp / unitScale / reduce",
    text: "where 按非零条件替换；条件或替代值缺测时保留原值，原图缺测像素不会复活。clamp 截断范围，unitScale 只线性缩放、不自动截断；要求有限 low < high。Image.reduce 对波段归约，输出以 reducer 名命名。当前以浮点计算值验收，不承诺所有 GEE 整数类型转换。CSV selectors 可选择和排列已有输出波段。",
    code: "var out = image.select('B8').unitScale(0,10000).clamp(0,1);\nout = out.where(out.gt(0.8), 0.8);\nvar average = image.select(['B8','B4']).reduce(ee.Reducer.mean());",
  },
  {
    id: "gee-training-schema",
    title: "训练字段与集合元数据",
    text: "train 省略 inputProperties 或传 null 时采用集合 band_order；顺序保留，不自动排除类别字段。有值的显式列表优先，空列表不触发自动选择。内联集合通过 set/setMulti 声明有限 JSON 元数据，筛选、limit、随机列和 map 到 Feature 保留；copyProperties 仅支持内联集合之间。Image.sample 声明已有波段，sampleRegions v1 仍需显式字段。动态取样元数据只读，尚无 Google 同数据对照。",
    code: "var training = training.set('band_order', ['nir','red']);\nvar model = ee.Classifier.smileRandomForest(50).train({\n  features:training, classProperty:'label'\n});\nprint(model.schema());",
  },
  {
    id: "gee-smile-rf",
    title: "随机森林训练与影像分类",
    text: "smileRandomForest 使用固定的本地 Smile 1.5.3。支持内联 FeatureCollection 或 sampleRegions 后 filter/无排序 limit 的训练表；训练字段为1–8个数值属性；省略 inputProperties 时采用集合 band_order 的完整顺序，训练标签为从 0 连续编号的 2–64 类。六个构造参数均参与实际训练，最多 256 棵树、1000 行，仍受工作预算限制。CLASSIFICATION 模式支持影像与表分类，以及训练重代入矩阵和验证指标；explain 和其他模式尚不支持；随机列使用已说明的本地算法。执行需要固定的本地 RF 运行包；源码/组件验证与本机部署验收分开记录，尚无 Google 同数据对照。",
    code: "// image、training 为已有影像和带 label 属性的训练表\nvar model = ee.Classifier.smileRandomForest({\n  numberOfTrees:100, variablesPerSplit:1, minLeafPopulation:1,\n  bagFraction:0.5, maxNodes:null, seed:42\n}).train({features:training, classProperty:'label',\n  inputProperties:['red','nir']});\nvar classified = image.classify(model, 'landcover');\nMap.addLayer(classified, {min:0,max:1,palette:['386a4d','d9b76e']}, '分类');",
  },
  {
    id: "gee-rf-validation",
    title: "分类验证与精度指标",
    text: "FeatureCollection.classify 保留原始字段、几何、ID 和顺序，并添加分类字段。输入为内联表或 sampleRegions/filter/limit 结果，缺少输入字段、输出重名和非有限数值会失败。errorMatrix 的行为实际类、列为预测类；显式 order 保留类别顺序。支持 array、order、accuracy、kappa、consumersAccuracy、producersAccuracy 和 fscore。训练 confusionMatrix 使用真实训练行重代入，不是独立验证集；各指标的形状与零分母规则遵循本地文档。getInfo 通过本地 JSON 任务返回结果，表导出仍为 CSV。分类后的 filter/limit、随机拆分和动态指标的通用算术尚未支持。",
    code: "// model、validation 为已有模型和独立验证表\nvar predictions = validation.classify(model, 'prediction');\nvar matrix = predictions.errorMatrix('label', 'prediction', [0,1]);\nprint('验证矩阵', matrix.array());\nprint('总体精度', matrix.accuracy());\nprint('训练重代入', model.confusionMatrix().array());\nExport.table.toDrive({collection:predictions, fileFormat:'CSV'});",
  },
  {
    id: "gee-image-sample",
    title: "影像像元取样",
    text: "Image.sample 默认遍历有限影像范围内的像元，也可显式指定 region。factor 与近似 numPixels 二选一，seed 固定本地抽样；不保证与 Google 抽中相同像元。dropNulls 默认删除任一波段缺测的行，false 保留空值；训练前用 notNull 清理。geometries=true 输出真实像元中心。返回 band_order，分类器省略 inputProperties 时采用其完整顺序；排除类别等字段时显式填写输入列表。结果最多1000行，近似抽样超过上限会报错。tileScale 仅支持1，投影与米制 scale 遵循本站网格限制。独立组件验证与完整任务运行验收分别记录。",
    code: "// image 和 roi 为已有的有限本地影像与研究区\nvar samples = image.sample({region:roi, numPixels:100, seed:42, dropNulls:false, geometries:true});\nprint('波段', samples.get('band_order'));\nExport.table.toDrive({collection:samples, fileFormat:'CSV'});",
  },
  {
    id: "gee-random-column",
    title: "随机列与训练／验证拆分",
    text: "FeatureCollection.randomColumn 支持 uniform 和 normal、种子及有序 rowKeys。默认使用已有 system:index；内联要素没有 ID 时须提供明确行键，不按行号伪造标识。相同行键与种子返回相同值，重排和筛选不会重抽；空值或复杂行键会报错。新列可被筛选、导出及训练使用，覆盖普通字段会保留列位置。使用本地固定算法，不保证与 Google 的随机值一致。表操作累计最多16步，资源预算可能限制有效行数。分类后的变换仍未支持。",
    code: "// samples 为已有取样表\nvar split = samples.randomColumn('split', 42);\nvar training = split.filter(ee.Filter.lt('split', 0.7));\nvar validation = split.filter(ee.Filter.gte('split', 0.7));\nvar model = ee.Classifier.smileRandomForest(50).train(training, 'label', ['red', 'nir']);\nvar predictions = validation.classify(model, 'prediction');\nprint(predictions.errorMatrix('label', 'prediction', [0, 1]).array());",
  },
  {
    id: "gee-levels",
    title: "兼容等级与当前限制",
    text: "官方客户端签名存在仅表示能构造语法。本站区分 S 语法、C 本地编译、E 实际引擎运行、N 独立数值参考、G 与原始 GEE 同数据对照；独立 JVM/tile 组件不等于完整任务引擎验收。函数清单由 /gee/v1/capabilities 返回，每项有参数限制。没有做过 GEE 对照的项目不能标成完全等价。不支持的算法或数据集会返回 EEUnsupported，禁止静默替代。",
  },
];
export default entries.map((d) => ({
  ...d,
  category: "GEE JavaScript",
  language: "javascript" as const,
}));
