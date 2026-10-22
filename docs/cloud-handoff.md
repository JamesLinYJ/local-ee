# 云端开发交接

2026-10-21。用户明确要求由云端 Codex 继续开发与兼容性测试，当前优先 GEE Python：先探测、整理 `docs/gee-python/list.md`，再持续补齐兼容。完整平台目标仍见 `GOAL.md`、`AGENTS.md` 和 `docs/architecture.md`，不能把本轮客户端接入当成整个目标完成。

## 2026-10-22 云端续作

阶段范围已按用户最新要求调整：先完成 Python API／参数／计算语义兼容，再推进 JS；Linux 隔离执行、macOS／ARM64 及本机真实数据验收延期，不作为当前阶段前置条件。暂不开发新隔离适配器，继续运行便携兼容层与可信合成数值测试，保留现有运行器及沙箱检查。下文历史未运行记录继续保留，不代表当前目标受阻。

已从 `handoff/gee-python-cloud-20261021` 的 `71810c3448241051696545d0810f5348f1875290` 核对并继续。Linux 使用 Python 3.11、Node 24、uv 0.12.12；锁定依赖和便携测试环境已经实际验证，完整原生服务仍未在 Linux 适配。

本轮补齐公开 Python API／参数／绑定清单，修复命名 GeoJSON CRS、notNull、Dictionary／List.sequence，增加有界 ImageCollection 元数据 Join 和静态 Array／矩阵求值；独立数值参考只覆盖明确的静态算法／合成图。探针保持原有 50 个表达式，当前 44 项编译通过、6 项明确拒绝，不能据此推算完整 API 兼容率。完整清单和剩余限制见 `docs/gee-python/list.md`。

验证汇总见 `reports/gee-python-wave1.json`：Python 597 passed／7 skipped，前端 11 passed、TypeScript／构建通过；包含 8 项固定 Python／JS SDK 的共享编译结果回归。没有运行完整 Linux 后端、macOS 内核沙箱、ARM64 JNI 或私有影像验收。

探针守卫发现原 SDK 的可选弃用资产初始化会通过 urllib 请求 Google STAC；本地初始化现已跳过这项云目录操作，生产路径初始化／重置有网络入口拒绝回归。计数覆盖 Python transport／socket／DNS，并非内核抓包或用户程序隔离。

`GOAL.md` 已按用户要求持久化“Python 完整优先，随后 JS”的持续目标；文件本身记录目标与验收条件，后台任务状态以运行平台为准。

## 第二批 Python 兼容实现

第一批已验证提交 `6cd97801e5685dfb4c9e365f1328d321c369d0a8` 已在临时验证分支取得精确提交的 `python`／`frontend` 成功后，快进发布到 main。交接分支名保留为开发分支，不能据其远端位置判断 main 的最新状态。

第二批增加有界内联 FeatureCollection 操作、无权表格 linearFit／linearRegression、maxDifference 数值度量和 saveBest、Number.format 十进制子集及 String 构造／拼接预算。版本化合成表格示例串联筛选、OLS、矩阵预测和格式化，使用手算系数与 RMS 验证。详见 `reports/gee-python-wave2.json` 和 `docs/gee-python/list.md`，表格静态求值不构成栅格引擎验收。

本批 Linux Python **709 passed／7 skipped**；前端 **11 passed**，TypeScript／生产构建通过。7 项跳过仍为 3 项 opt-in JVM/Spark 和 4 项 macOS Seatbelt 检查。`uv sync --frozen --python 3.11`、`npm ci`、探针漂移检查和 Python API 清单字节重现均通过。

原有 50 项表达式保持不变，当前 45 项编译通过、5 项拒绝；其中影像集合回归仍明确拒绝，新增表格回归不能替代它。Python／JS 官方 SDK 共享回归增至 13 项，完整 JS 目标仍排在 Python 之后。后续委派子 agent 按用户要求固定使用 Luna、max 推理，文件所有权不得重叠。

Linux 用户／挂载／PID namespace 的临时能力探测在执行沙箱外成功；普通执行沙箱内的 `/proc/self/uid_map` 写限制不能推断为内核不支持。尚无验收通过的 Linux 执行适配器，因此生产用户代码继续拒绝在无对应原生隔离的平台执行。

## 第三批时间匹配工作流

第二批提交 `76fe99a271731e2e8e319195191fec5187ba9ea0` 已通过精确提交的 GitHub `python`／`frontend` 检查并快进发布到 main。第三批在此基础上将 Join 条件验证／求值拆到 `join_conditions.py`，增加唯一 maxDifference 与标量条件的 And 组合，以及有限 ImageCollection 的 `Join.inner`。不请求度量时保留 Or／Not 布尔筛选；请求度量时拒绝多重或歧义结构。

inner 输出匹配对 Feature，内部保留真实 Image；Feature 属性和同类 Image 映射结果可继续进入选波段、addBands、ImageCollection 计算。版本化 `ee-temporal-interpolation-v1.json` 串联最近前后观测、毫秒权重和像素插值，独立参考同时覆盖来源、掩膜和目标时间。详见 `reports/gee-python-wave3.json`；这些合成图数值测试不是原生栅格引擎执行。

本批 Linux Python **745 passed／7 skipped**，前端 **11 passed**、TypeScript 和构建通过；比第二批增加 36 项通过回归，跳过项目及原生平台限制不变。原大输出预算用例采用数值匹配键以单独命中物化／1 MB 上限；字符串扫描预算另有明确负控，没有放宽失败断言来隐藏回归。

原有 50 项表达式及 45 编译通过／5 拒绝不变，Python／JS 官方 SDK 共享编译回归增至 15 项。后续继续优先 Image.array*、逐像元回归、采样／分类训练预测与真实项目，Python 完整目标仍未完成。

## 第四批静态数组与 PCA

第三批提交 `ca9fdc9a9e0215e5ef98befd93a58e9f0f82d6b9` 已通过精确提交的 GitHub `python`／`frontend` 检查并快进 main。第四批在此基础上将 Array 类型／资源校验、布局、算术、归约及矩阵分解拆为独立模块，保留原导出与已有矩阵调用。

增加 19 项有限静态 Array 方法：同形算术、slice／project／repeat／cat、单输出 reduce／accum、实对称 eigen、Cholesky、行列式／迹／对角线／Frobenius 范数。版本化静态 PCA 串联中心化、样本协方差、投影、重建，并以独立闭式结果验证。审查发现的极值求和／均值抵消、中位数和矩阵迹中间溢出已修复，有限结果与真实溢出均有回归。方法存在、矩阵内核和静态 N 均不能代替 Image.array* 或栅格引擎验收。

本批 `uv sync --frozen`、全套 Python **830 passed／7 skipped**、`npm ci`、前端 **11 passed**、TypeScript／构建均通过。固定 Python 清单独立进程字节重现通过；原 50 探针仍为 50 S／45 C／5 拒绝，Python／JS 共享编译回归增至 19 项。新增参数限制、浮点／特征向量呈现政策和未运行项目见 `reports/gee-python-wave4.json` 与 `docs/gee-python/list.md`。

整体目标保持进行中。当前限制针对 Linux 隔离和原生平台／真实数据／Google 对照验收，离线兼容开发可以继续；仍需推进栅格数组、逐像元回归、分类及真实遥感全流程。

## 获取正确状态

- 仓库：https://github.com/JamesLinYJ/local-ee
- 已发布基线：`d774f01af26dc002d3193fdd2c4c7f035c277b2b`，包括 `130b527` 的 Python 官方客户端、常量波段及 Float64 归约，以及 Python 地图事件前端。该基线的 GitHub `python`、`frontend` 检查通过。
- 从 `handoff/gee-python-cloud-20261021` 分支继续；这个分支包含交接时尚未完成的 Python 探针和 notNull 改动。先检查分支最新提交，不要只克隆旧 main。
- 交接时已无存活的开发子 agent；不需要等待旧 agent 句柄。本机工作台服务不是这些开发子任务的一部分。

## 已有实现和证据

官方 `earthengine-api` 1.7.49 固定到 Google 上游提交 `e189e4b89e785019ea5642ea8e80cb644749cd4a`，与 JS 相同。Python 运行器保留 openEO `connection`，注入本地 `ee` 和 `Map`。官方 SDK 构造表达式；共享编译器负责实际支持的算法。禁止默认 Google OAuth、项目发现与公网回退。

- 模块：`gee/ee_python_{client,transport,tasks,exports,map}.py`，每个约 150–200 行。
- 后端：`gee/services/ee.py`、`ee_events.py`、`ee_idempotency.py`，父脚本权限校验、地图事件预算、数据库持久化请求去重。
- 本机数据库迁移 v4 仅新增请求唯一索引；升级前已备份，本机记录数量保持不变。
- 报告：`reports/gee-python-client.json`、`reports/gee-constant-wave5.json`。
- 原生 macOS 实测：Python SDK 的值读取、地图、Task 启停／状态／列表、GeoTIFF／区域 CSV 下载、四路相同请求去重；Edge 示例运行并显示地图和下载入口。
- 常量／日期波段：14 个用例、18 个输出波段，独立 NumPy/Rasterio 比较为零掩膜和数值差异；没有 Google 同数据比较。
- 交接时应用测试为 412 passed / 3 skipped（另有真实内核／SPI 检查）；前端 11 项测试、TypeScript、构建通过。

## 初始交接问题及当前状态

1. 初始 50 项草稿为 38 编译通过／12 拒绝，旧硬编码网络计数不构成证据。现已拆分模块、补专用重复性／漂移测试与 deny/count 守卫，v2 仍保留原表达式，并分开标注未运行的 E/N/G。
2. Python 命名 GeoJSON CRS 引起的 unhashable dict 已修复，四个相关原探针通过；只接受明确的有限二维 EPSG:4326 平面范围，其他语义拒绝或列为未验证。
3. Filter.notNull 已补专用回归、能力登记与预算；本地平面属性名 S/C 验证，无 Google 对照。
4. Dictionary 空 keys／缺键和 List.sequence count 已补；有限元数据 Join、静态矩阵也已补。栅格数组／回归、分类器、空间／时间度量 Join、邻域／高级时序仍有实质缺口。
5. `reports/gee-python-api-inventory.json` 已生成 991 项签名／2451 参数和公开 Python 绑定目录；列出方法不等于实现所有重载或后端算法。

## 云端起步

先读 AGENTS，再使用仓库固定依赖和 CI 命令：

```sh
python3.11 -m pip install uv==0.12.12
uv sync --frozen
.venv/bin/python -m pytest -q
cd web
npm ci
npm test
npm run build
```

使用 Python 3.11、Node 24；安装过程需要官方 GitHub 和包仓库。不要自行替换锁定的 SDK、Spark 或 Scala 版本。探针脚本作为模块运行：`.venv/bin/python -m scripts.ee_python_probes`。运行前后比较生成夹具，并为失败类型增加测试。

Linux 云端继续完成 SDK、纯编译、权限服务单测、前端和合成数值测试。本阶段不实施新的 Linux 隔离执行适配，macOS Seatbelt、ARM64 JNI 与本机真实数据验收延期；这些延期不阻断兼容开发，也不要求每批重复验收。可用的可信引擎数值测试与用户脚本运行器验收分别记录，保留已有沙箱检查；跳过或未运行项目不能标为通过。

本机账号、密钥、数据库、原始影像和私有审计目录没有上传。云端先使用版本化合成样本。不要索取／复制本机凭据，也不要恢复用户已删除的旧数据库。

## 持续实施要求

按清单完成每个真实工作流；保持 Python 优先并保留 JS。允许多个子 agent 分工，但源文件所有权不重叠，多数模块约 150–250 行，超过 400 行通常先拆分。及时清理生成的缓存、重复下载和构建副本，保留必要证据。

用户授权直接 push，不需要 PR。保护 main 的规则仍有效：先在验证分支对精确提交取得 `python`／`frontend` 成功，再快进 main，删除临时验证分支；不强推、不绕过保护。没有远端写权限时保留可审查的提交／补丁并准确报告，不把未推送说成已发布。
