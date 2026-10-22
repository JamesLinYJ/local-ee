# Image.sample 与采样随机森林

本页记录第二十八批 Image.sample 工作流。它从一张有限范围影像读取真实栅格像元，生成有界样本表，再接入已有 Smile 随机森林训练、要素预测、混淆矩阵、地图和本地导出图。版本化合成样本不代表已入库卫星数据。

## 示例

[完整 Python 示例](../../examples/33_GEE_python_image_sample.py) 从固定影像选择 landcover、nir、red，使用 Image.sample 取样，依次执行 Filter.notNull、数值筛选和 limit，然后显式以 inputProperties=['nir', 'red'] 训练 Smile 随机森林。之后用独立验证要素计算错误矩阵和访问器，并生成分类影像、Map 图层、CSV 样本表和 GeoTIFF 导出图。

示例提供四种互不混用的取样模式：

| 模式 | 取样选项 | 用途 |
| --- | --- | --- |
| all | 默认整幅有限 footprint；不设 factor／numPixels；默认 dropNulls=True | 检查全像元和默认掩膜删除 |
| nullable | 全部 footprint；明确 dropNulls=False | 让 NoData 变成 null 属性，再由 notNull 清理 |
| factor | factor=0.5、固定 seed=7、显式 ROI | 检查按全局网格坐标稳定的比例取样 |
| num_pixels | numPixels=8、固定 seed=7、显式 ROI | 检查近似目标数量和取样前总体数量 |

官方 Python SDK 的参数名与默认值来自固定版本 earthengine-api。示例将 tileScale 固定为 1；输出像元中心可用 geometries=True 保留为点几何。要使用实际本地数据，请将示例影像和验证要素换成自己的有效对象。

## 参数、网格与空值

- region 省略时取该影像已知的有限 footprint；显式 ROI 必须是受支持的内联几何。多边形按像元中心覆盖选择，边界上的中心计入；点／多点沿用当前本地半开网格归属规则。跨 tile 执行仍由同一全局行列坐标确定选择。
- 省略 scale／projection 使用影像当前网格。显式设置支持 EPSG 投影和米制 scale，并沿用已有 `resample_spatial` 最近邻路径；native 侧还会把请求网格与实际像元网格核对。单独指定 projection、在地理坐标系 EPSG:4326 使用米制 scale，或实际网格不匹配时会明确失败。完整 Earth Engine 网格行为仍未验证。
- factor 接受 (0, 1] 的有限值；numPixels 接受 0..1000 整数。二者互斥。numPixels 是近似目标，候选总数为 ROI 覆盖的全部栅格像元数，包含掩膜像元；它不能保证返回指定行数。筛选和掩膜处理后如超出输出行上限，任务整体失败，不截断或重抽样。
- seed 是有符号 32 位整数，默认 0。当前本地算法 splitmix64-grid-v1 对全局列、行和 seed 计算确定性哈希，再与 factor 或 min(1, numPixels / population) 比较。选择先于 dropNulls；分区顺序和 tile 遍历不会改变候选行。
- dropNulls=True 会删除任何所选波段含 NoData 的样本；False 保留 null 属性，之后可显式用 Filter.notNull 筛选。有效 Infinity 拒绝。无样本时返回空表；numPixels=0 的结果也为空。
- tileScale 仅支持 1。geometries=True 返回真实像元中心，不合成虚假坐标。band 顺序按输入影像顺序保留。

哈希和 ROI 候选数的独立实现位于 [原始网格参考代码](../../tests/ee_image_sample_reference.py)，固定原始值和各模式的候选 ID／类别频数位于 [v1 夹具](../../tests/fixtures/ee-image-sample-rf-v1.json)。该参考从源数组枚举每个网格像元中心，独立实施 ROI 覆盖、哈希、掩膜、filter 和 limit；它用于检查声明的本地算法，不表示 Google 的随机数生成器、选中行或几何边界与本地相同。

## 训练、预测与元数据

Image.sample 的输出继续使用现有采样表类型和预算，随后可接已支持的样本筛选、限量、训练和结果路由。随机森林必须显式提供 inputProperties；示例通过波段名选择 [nir, red] 输入，目标影像原始顺序为 [red, nir]，验证按名称对应。

样本表元数据 get('band_order') 返回选中波段的有序列表；propertyNames() 返回由采样规格声明的 collection 元数据名。它们只读规格元数据，不读取或虚构任何像元值。特征行仍由实际取样任务产生，getInfo() 不在编译阶段生成训练数据。

示例的分类器验证使用独立的固定验证要素，保留类顺序 [0, 1]，并分别编译预测、错误矩阵、矩阵数组、顺序、准确率、Kappa、用户／生产者精度和 F-score 访问器。训练重代入矩阵通过随机森林分类器本身的 confusionMatrix() 路由。

## 地图与导出

Map.addLayer、Export.table.toDrive 和 Export.image.toDrive 都从同一工作流生成。CSV 选择 system:index、样本波段和 .geo；影像导出采用 GeoTIFF 和明确 region。示例只创建未启动的任务对象；此 toDrive 兼容路径写入本地任务结果，不会上传 Google Drive。

本批 workflow 测试检查 Python 与官方 JavaScript SDK 序列化后得到相同的本地编译图，并用独立原始栅格参考核对样本 ID、顺序、数值、null、factor 和近似 numPixels 选择。该测试不访问 Google 服务。真实 native tile 执行由独立引擎验证记录，不能由编译或测试 oracle 替代；完整 Spark／批任务／沙箱／浏览器／部署以及 Google 同数据对照应分别记录。

## 限制

工作流仍受现有 1000 行、256 列、50000 行列单元、JSON／CSV 字节、表达式、采样工作和图节点预算限制。多预算叠加时，单个限制未超也可能整体拒绝。当前没有跨 tile 邻域计算、随机森林自动 schema、其他 RF 模式或 Google 随机子采样等价保证。Image.sample 的方法可见、图成功编译和样本元数据可读取，都不等于完整 Python API 或 Google 计算兼容。
