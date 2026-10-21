# GEE Python 兼容清单

状态：云端交接初版，2026-10-21。优先 Python，持续保留 JS；未完成整体兼容。

S＝官方客户端实际序列化；C＝本地编译；E＝实际引擎；N＝独立数值基准；G＝Google 同数据对照。算法签名有 991 项，下面仅为 50 个定向调用，不能换算为全 API 兼容百分比。

## 已验证基线

- [x] 官方 Python SDK 固定版本、离线初始化、共享本地 EE 编译器。
- [x] 本机 Python getInfo、地图、任务启动／状态／取消／列表。
- [x] 本机 GeoTIFF 与区域 CSV 输出及 HTTP 下载校验。
- [x] 数据库请求去重、父脚本范围与地图事件预算回归。
- [ ] 全 991 项签名、Python 类型／方法／参数绑定和重载清单。
- [ ] 所有声明支持项的 E／N 和错误／边界验收。
- [ ] Join、矢量批量统计、数组矩阵、回归、分类、邻域和高级时序。
- [ ] 云端 Linux 执行隔离和引擎验收；不能替代本机 macOS 验收。
- [ ] Google 同数据数值比较。

## 当前 Python 调用探针

草稿来源：`tests/fixtures/ee-python-1.7.49.json`。50 个 S、38 个 C 通过、12 个 C 拒绝；尚需专用回归、可重复性和调用边界检查。导出行只检查表达式与本地参数准备，不能当成额外运行验收。

| 调用 | S | C | 当前输出或失败原因 |
| --- | --- | --- | --- |
| `number_add` | passed | passed | 9 |
| `number_divide_format` | passed | rejected | Unsupported algorithm arguments: ['number', 'pattern'] |
| `date_get_year` | passed | passed | 2023 |
| `date_difference_days` | passed | passed | 1.0 |
| `date_advance` | passed | passed | 2023-11-16T00:00:00.000+00:00 |
| `list_map_lambda` | passed | passed | [2, 4, 6] |
| `list_iterate_lambda` | passed | passed | 6 |
| `dictionary_get` | passed | passed | 4 |
| `conditional` | passed | passed | yes |
| `geometry_rectangle` | passed | passed | {"coordinates": [[[100.1, 30.1], [100.9, 30.1], [100.9, 30.9], [100.1, 30.9], [100.1, 30.1]]], "type": "Polygon"} |
| `collection_load` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `filter_date` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `filter_bounds` | passed | rejected | Malformed or unsupported Earth Engine expression: unhashable type: 'dict' |
| `filter_metadata` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `filter_and_sort` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `select_named_bands` | passed | passed | ["NIR", "RED"] |
| `map_ndvi_copy_properties` | passed | passed | ["NDVI"] |
| `expression_ndvi` | passed | passed | ["NDVI"] |
| `addbands_constant_named` | passed | passed | ["red", "constant"] |
| `update_mask` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `unmask_fill` | passed | rejected | Image.unmask sameFootprint=false with a global footprint is not supported |
| `where_threshold` | passed | passed | ["nir"] |
| `clip_region` | passed | rejected | Malformed or unsupported Earth Engine expression: unhashable type: 'dict' |
| `reduce_region_named` | passed | rejected | Malformed or unsupported Earth Engine expression: unhashable type: 'dict' |
| `collection_mean` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `collection_median` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `collection_max` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `collection_mosaic` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `quality_mosaic` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `collection_count` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `collection_to_bands` | passed | passed | ["scene-a_nir", "scene-b_nir", "scene-c_nir"] |
| `collection_from_images` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `collection_limit_sort` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `map_copy_system_properties` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `map_set_dynamic_property` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `map_arithmetic_rename` | passed | passed | ["reflectance"] |
| `first_dynamic_property` | passed | passed | scene-a |
| `aggregate_array_properties` | passed | passed | ["scene-a", "scene-b", "scene-c"] |
| `filter_date_algorithm` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `map_expression` | passed | passed | ["difference"] |
| `image_band_names` | passed | passed | ["blue", "green", "red", "nir", "SCL"] |
| `image_to_float` | passed | passed | ["nir"] |
| `neighborhood_reduce_kernel` | passed | rejected | Unsupported Earth Engine algorithm: Kernel.square |
| `focal_mean` | passed | rejected | Unsupported Earth Engine algorithm: Image.focalMean |
| `join_save_first` | passed | rejected | Unsupported Earth Engine algorithm: Join.saveFirst |
| `array_matrix_multiply` | passed | rejected | Unsupported Earth Engine algorithm: Array |
| `regression_reducer` | passed | rejected | Unsupported reducer: Reducer.linearRegression; stdDev cannot be mapped to sample standard deviation |
| `classifier_constructor` | passed | rejected | Unsupported Earth Engine algorithm: Classifier.smileRandomForest |
| `export_image_drive` | passed | passed | ["NIR"] |
| `export_table_drive` | passed | rejected | Malformed or unsupported Earth Engine expression: unhashable type: 'dict' |

## 首批修复顺序

1. 修复 Python 几何／投影序列化造成的 dict 解码异常，增加合法和非法输入回归。
2. 完成 Filter.notNull，并补 Dictionary 空 keys／缺键与 List.sequence 的参数行为。
3. 补全 Python 全量 API 和参数清单，再按实际工作流完成 Join、数组回归及其他算法。
4. 每批做 S／C、E／N 分层验证，更新本文件；不能仅将未支持方法加入 handler 表。

交接与云端测试方法见 [cloud-handoff.md](../cloud-handoff.md)。已有运行证据见 [Python 客户端报告](../../reports/gee-python-client.json) 和 [常量／Float64 报告](../../reports/gee-constant-wave5.json)。
