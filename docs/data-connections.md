# 数据和外部连接

分析服务仅访问本地 PostgreSQL、目录和任务文件。GeoTrellis 容器使用 `network=none`；Python 容器仅加入内部网络，只能连接本地 API，既没有数据目录挂载，也没有数据库或供应方凭据。浏览器脚本、样式、字体、示例和网格底图均在本机，CSP 只允许同源连接。地名搜索不接入外部服务。

`compose.sync.yaml` 是单独的数据同步配置。当前验收期间该出口已停止，需管理员主动启动：`docker-compose -f compose.yaml -f compose.sync.yaml up -d egress sync`。供应方连接通过精确主机名白名单的 HTTPS CONNECT 代理；只放行 443，拒绝跳转至未配置的主机。TLS 证书由客户端正常验证，代理不解密内容。

| 供应方 | 地址 | 外发内容 |
|---|---|---|
| Earth Search STAC | earth-search.aws.element84.com | 数据集、研究区包围盒、日期、云量过滤和分页参数 |
| Sentinel-2 Collection 1 COG | e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com | 公开资产路径和字节范围 |
| 旧 Sentinel COG（仅审计历史样本） | sentinel-cogs.s3.us-west-2.amazonaws.com | 同上；新接入器拒绝旧 L2A 集合 |
| Planetary Computer | planetarycomputer.microsoft.com | Landsat/DEM 检索参数及资产签名请求 |
| Landsat / DEM 资产 | landsateuwest.blob.core.windows.net、copdem30m.blob.core.windows.net | 资产路径、签名查询参数、字节范围 |
| CDS / ECMWF | cds.climate.copernicus.eu、object-store.os-api.cci2.ecmwf.int | ERA5-Land 检索参数与用户主动配置的供应方认证 |

这些请求不是匿名的：供应方可以看到请求来源 IP、区域、时间和变量。Python 脚本正文、分析结果、工作台账号和本地日志不作为遥测发送。ETL 计费上报、外部日志接收端、OIDC、OTLP 导出均未配置；引擎网络隔离作为第二层控制。

此 Mac 的 DNS 代理使用 `198.18.0.0/15` 假 IP，因此本地 `.env` 设置 `ALLOW_FAKEIP_DNS=1`。只有上述精确白名单域名能使用它，RFC1918、环回和链路本地目标仍拒绝。没有这种 DNS 代理的部署应保持 0。

## 标准化规则

- 本地 `sentinel-2-l2a` 对应上游 **sentinel-2-c1-l2a**。只接受 Collection 1，按每个资产 `raster:bands` 的 scale/offset 转换，SCL 保留 4、5、6、7；NoData 为 -9999。保留 7（未分类）是本版质量策略，严格研究可另行筛选。禁止混入旧 Earth Search L2A，其偏移标记存在已知歧义。
- Landsat C2 L2 接入器提供反射率缩放和 QA_PIXEL / QA_RADSAT 掩膜，尚未完成真实样本验收。
- Copernicus DEM 接入器使用米，尚未完成真实样本验收。
- ERA5-Land 保留原始 NetCDF；t2m 从 K 转换为摄氏度，00–23 UTC 完整 24 小时求日均；缺小时为 NoData。降水使用次日 00 UTC 累计量，m 转 mm，不能逐小时累加累计字段。月统计需完整的日序列。用户本次选择暂不配置 CDS，真实下载未验收。
- 配置中的日期上限用于供应方查询时包含该日；openEO `temporal_extent` 的结束点不包含。
- 默认示例范围 113.55–113.57E、22.30–22.32N 是公开演示区域。不是用户提供的研究区。
- 下载源元数据、处理规则、坐标系、网格、单位、COG SHA256 均保留。修订版作为不可变文件保存，新查询只选择 active 版本；旧任务保存提交时的快照。

同步使用分页，重试与去重；`max_items` 超限会明确失败并保留已入库数据。大文件下载支持 ETag/Range 续传与长度/SHA256 校验。光学影像按研究区读取 COG 字节范围，失败后重新读取未完成景；不会下载全球影像。
