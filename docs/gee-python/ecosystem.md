# GEE 兼容与本地计算项目核对

核对日期：2026-10-22。本次范围为 GitHub 仓库检索、项目 README 和相关源码，不是穷尽全网的调查。未安装或运行下列外部项目；项目提供的能力不等于本仓库已集成或已验收的能力。

| 项目 | 从公开资料确认的方向 | 与 Local EE 目标的关系 |
| --- | --- | --- |
| [google/earthengine-api](https://github.com/google/earthengine-api) | 官方 README 明确为调用 Earth Engine API 的 Python／JavaScript 客户端库 | 复用客户端构造、类型和序列化；该仓库没有提供可直接启动的完整本地计算服务端 |
| [gee-hydro/gee-local.ts](https://github.com/gee-hydro/gee-local.ts)（当前 README 名称为 gee-helper） | 本机运行 Code Editor 风格 JS、注入 Map／Export／Chart、处理 require 包与导出；ee-auth 依赖官方 JS SDK 和 Google 认证。另有 catalog／crop／applyLocal 接口调用 Julia 本地栅格处理 | 可以参考脚本宿主与模块加载设计。其本地数据接口是另一套调用路径；已读资料没有证明普通 ee.* 表达式被完整映射成本地算法。Google OAuth／远端导出路径不符合本项目离线运行约束 |
| [Open-EO/openeo-geopyspark-driver](https://github.com/Open-EO/openeo-geopyspark-driver) | 使用 GeoPySpark／GeoTrellis 执行栅格计算的 openEO 后端 | 本仓库已有的计算基础；继续复用数值和栅格组件，同时单独验证 EE 参数、掩膜、投影和集合语义 |
| [Open-EO/openeo-earthengine-driver](https://github.com/Open-EO/openeo-earthengine-driver) | 实现 openEO API，并使用 Google Earth Engine 作为执行后端，需要相应认证 | 接口转换方向与本项目不同；不能据名称推断它提供离线 GEE 服务端 |
| [gee-community/geemap](https://github.com/gee-community/geemap) | README 说明围绕 Earth Engine 服务器提供 Python 交互分析和可视化 | 可参考客户端使用场景和工作流，不把可视化封装算作本地算法实现 |
| [google/Xee](https://github.com/google/Xee) | 将 ee.Image／ImageCollection 打开为 Xarray 数据集；示例初始化 Google 项目和 Earth Engine endpoint，并从服务端读取像素 | 有助于理解 Python 科学计算接口，但不是离线替换 Earth Engine 计算服务端 |
| [opendatacube/datacube-core](https://github.com/opendatacube/datacube-core) | 以自己的 API 提供格网化地球观测数据分析环境 | 可复用的数据立方体思路与组件；不将其自身 API 视为 EE API 兼容证据 |

结论限定为：相关项目和可复用组件已经存在；本次检索没有确认到一个成熟、完整、可离线直接替换 GEE 服务端并保持其全部 API 语义的实现。这个结论不能推断“没有人尝试过”，也不说明本项目接近完成。

Local EE 的工程方向仍是复用官方客户端和已有计算后端，在统一兼容层实现并验证 EE 特有的行为。已有 TypeScript 网页通过现有接口使用后端；Python／JS 官方序列化回归保护共享计算路径。全量签名清单是长期追踪范围，交付证据按真实工作流及 S／C／E／N／G 分开记录。

核对入口：[官方客户端 README](https://github.com/google/earthengine-api/blob/HEAD/README.md)、[gee-local 本地宿主说明](https://github.com/gee-hydro/gee-local.ts/blob/HEAD/docs/local-runtime.md)、[ee-auth 依赖声明](https://github.com/gee-hydro/gee-local.ts/blob/HEAD/packages/ee-auth/package.json)、[独立本地数据接口](https://github.com/gee-hydro/gee-local.ts/blob/HEAD/src/data/local.ts)，以及表中各项目 README。链接跟随上游 HEAD，后续采用代码前需重新核对版本、许可和行为。
