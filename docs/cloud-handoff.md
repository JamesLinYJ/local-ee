# 云端开发交接

2026-10-21。用户明确要求由云端 Codex 继续开发与兼容性测试，当前优先 GEE Python：先探测、整理 `docs/gee-python/list.md`，再持续补齐兼容。完整平台目标仍见 `GOAL.md`、`AGENTS.md` 和 `docs/architecture.md`，不能把本轮客户端接入当成整个目标完成。

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

## 未完成工作和已知问题

1. `scripts/ee_python_probes.py` 与 `tests/fixtures/ee-python-1.7.49.json` 是草稿：50 个官方 Python 调用完成序列化，38 个表达式编译通过、12 个拒绝。尚缺专用回归测试、可重复性检查和模块整理。`network_requests: 0` 目前是草稿中的固定字段，不能据此声称已经抓取／核验运行流量。生成器通过受控源码字符串构造 SDK 对象，不接收用户程序。
2. 其几何输入触发 `unhashable type: dict`，影响 filterBounds、clip、reduceRegion 与表格案例；优先定位官方 Python GeoJSON／投影序列化的解码问题，不能以改坏探针、删参数来制造通过。
3. `gee/compat/earthengine/filtering.py` 有未完成的 `Filter.notNull` 实现。还没有专用测试、能力登记与正式验收。补齐缺失／null、0／False／空字符串、多字段、空列表和预算控制后再声明支持。
4. 已定位但尚未修改：`Dictionary.values(keys=[])` 误返回全部值；缺键 `Dictionary.get` 的默认值行为需按固定官方语义验证。`List.sequence(count=...)`、Join、数组／矩阵、回归、分类器、邻域／高级时序仍有实际缺口。
5. 全量 Python API／类型／方法／参数清单尚未生成。固定算法签名共有 991 项，现有 `reports/gee-api-inventory.json` 可复用结构；区分方法可见、序列化、编译、实际执行、独立数值验证和 Google 对照，不能用 handler 数量推算兼容率。

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

Linux 云端可以完成 SDK、纯编译、权限服务单测、前端和合成数值测试。macOS Seatbelt、现有 ARM64 JNI 与本机真实数据验收不能由 Linux 的跳过测试替代。需要引擎计算时，先建立独立的 Linux 执行／隔离适配器并验收；不得删除 macOS 沙箱、退回无隔离执行，或把新平台差异伪装成已通过。

本机账号、密钥、数据库、原始影像和私有审计目录没有上传。云端先使用版本化合成样本。不要索取／复制本机凭据，也不要恢复用户已删除的旧数据库。

## 持续实施要求

按清单完成每个真实工作流；保持 Python 优先并保留 JS。允许多个子 agent 分工，但源文件所有权不重叠，多数模块约 150–250 行，超过 400 行通常先拆分。及时清理生成的缓存、重复下载和构建副本，保留必要证据。

用户授权直接 push，不需要 PR。保护 main 的规则仍有效：先在验证分支对精确提交取得 `python`／`frontend` 成功，再快进 main，删除临时验证分支；不强推、不绕过保护。没有远端写权限时保留可审查的提交／补丁并准确报告，不把未推送说成已发布。
