# 管理与认证组件选型

2026-10-21。Refine 管理界面与本地角色认证已接入；文件模块见 [数据集与文件管理](dataset-files.md)。Keycloak OIDC 与 PgSTAC 尚未接入，不能将目标架构当作已部署事实。

## 选择

本平台采用 **Keycloak（身份）+ Refine Core（React 管理界面）+ 本平台管理 API（业务权限）+ STAC/PgSTAC 目录适配器（地学索引）**。保留现有 openEO、计算隔离、账号内部 ID 和科研数据。各组件可以独立升级，供应方凭据不进入管理前端。

| 开源组件 | 提供什么 | 本平台仍需实现什么 |
| --- | --- | --- |
| [Keycloak](https://github.com/keycloak/keycloak)，Apache-2.0 | 自建登录、用户/组、MFA、会话、OIDC/SAML | OIDC 回调与身份映射、应用对象权限、停用用户后的本地会话失效 |
| [Refine Core](https://github.com/refinedev/refine)，MIT | React/TypeScript 管理资源、数据与认证适配接口 | 实际后端认证、数据权限、科学元数据校验及符合现有界面的表单 |
| [stac-fastapi-pgstac](https://github.com/stac-utils/stac-fastapi-pgstac)，MIT；[PgSTAC](https://stac-utils.github.io/pgstac/pgstac/) | STAC API、Collection/Item 存储与时空检索 | 入库处理、校验、发布流程、业务级身份/权限和管理界面 |
| [GeoNode](https://docs.geonode.org/)，[许可证头声明 GPL-2.0-or-later](https://github.com/GeoNode/geonode/blob/master/LICENSE)，部署前核对固定版本及组件清单 | 完整 GIS 门户，包含用户、组、数据上传、元数据、权限及管理后台 | 与 openEO 的目录和数据版本对接、已有界面和账号迁移、额外服务运维 |

GeoNode 最接近“现成的带认证的数据管理系统”。对于从零建设 GIS 数据门户，它值得优先试用。本项目已经有 React 工作台、隔离计算和数据链路，重新引入一套门户与其存储/身份组件会增加集成边界，因此选择组件组合。此项是基于本项目现状的工程判断，并非声称 GeoNode 不适合生产。

Refine 的 AuthProvider 是认证适配接口，不是身份服务器；AccessControlProvider 也不能代替后端授权。PgSTAC 的数据库角色不等于用户或项目的数据集权限。免费开源核心足以作为当前管理模块基础，不依赖商业 RBAC 扩展。

## 身份和权限边界

- 身份服务：生产采用内网 Keycloak，OIDC 授权码 + PKCE；使用成熟 OIDC 库验证签名、issuer、audience、state、nonce。浏览器使用本平台 HttpOnly 会话，不持久保存供应方或 IdP 管理令牌。
- 本地账号继续保留，使用原内部 ID。外部身份通过 `(issuer, subject)` 映射；不自动按相同邮箱合并，也不将第一个 OIDC 登录用户自动提升为管理员。
- 角色：`admin` 管系统、用户和全局任务；`dataset_manager` 管数据目录和发布；`researcher` 运行研究任务；`viewer` 只读。后续项目/数据集授权是独立对象关系，不能靠角色字符串推断某个私有数据集可见。
- 账号禁用或降权需在后端立即生效；脚本令牌无管理权限。至少保留一个启用的管理员。
- 管理事件由服务端在同一事务写入审计记录；只记录允许的字段和对象 ID。页面不能修改审计记录。数据库层防篡改、异地归档和保留周期作为独立生产验收项。

## 管理员添加数据集

1. 创建目录草稿，登记 ID、名称、说明、来源与许可证。
2. 选择明确支持的本地文件入库或供应方同步方式；上传/暂存与正式资产分开。远程 URL 不直接交给计算引擎。
3. 独立入库任务检查格式、校验和、CRS、网格、波段、单位、缩放、NoData、时间与处理记录；读取外部格式的进程使用有限资源和驱动白名单。
4. 校验成功后生成版本化 COG/NetCDF 与 STAC Items；失败保留报告，草稿不可用于计算。
5. 管理员发布，指定可用范围。工作台和 openEO/EE 接口使用同一权限检查及固定版本快照。
6. 下架阻止新的检索与任务；既有结果和快照保留。物理删除、引用检查和保留周期单独设计，不将下架当删除。

普通“数据库增删改查页面”不能保证第 3 步的科学正确性。首批管理接口限制可编辑字段，已有数据的波段、尺度和掩膜不能被通用表单静默改写。

## 实施和迁移顺序

1. 先做版本化增量迁移、后端角色检查、数据集草稿/发布/下架、用户停用、任务与审计页面，形成可验证的管理闭环。
2. Refine 作为独立懒加载入口接入现有 React，用 `dataProvider/authProvider/accessControlProvider` 对接本地 API；显式设置 `disableTelemetry: true`，全部资源本地提供。
3. 接入并实测 Keycloak OIDC 的登录、登出、MFA、停用及旧账号映射。Keycloak 使用固定版本/摘要，分别验证 ARM64 和目标生产架构；不凭 Java 可移植性推断镜像已通过 ARM 验收。
4. PgSTAC 需要 PostGIS 等数据库扩展，现有普通 PostgreSQL 不视为已经满足。通过目录接口增量迁移，先在独立实例导入、比较 Item 数量/校验和/查询/权限，再切换；不直接替换现有数据库卷镜像。
5. 上线前补齐 TLS、最小数据库角色、备份恢复、磁盘配额、依赖处置和出站实测。组件支持这些能力不等于本平台已完成验收。

## 官方依据

- [Keycloak OIDC](https://www.keycloak.org/securing-apps/oidc-layers)：标准授权端点、授权码流程与令牌端点。
- [Refine AuthProvider](https://refine.dev/core/docs/authentication/auth-provider/)、[AccessControlProvider](https://refine.dev/core/docs/authorization/access-control-provider/)、[禁用遥测](https://refine.dev/core/docs/core/refine-component/#disabletelemetry)。
- [PgSTAC 数据库要求及角色](https://stac-utils.github.io/pgstac/pgstac/)。
- [GeoNode 管理后台](https://docs.geonode.org/projects/v4/en/4.4.x/admin/admin_panel/index.html)：用户、数据集、发布和权限管理。
