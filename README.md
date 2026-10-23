# Local EE

自托管遥感工作台：TypeScript + React 前端，Python/openEO 服务，GeoTrellis/Spark 本地计算。通过固定版本的官方 Earth Engine JavaScript／Python 客户端构造表达式，再由共享的本地兼容层执行已实现的算法。

当前部署目标是 **Apple Silicon macOS 原生运行**。脚本、入库和计算使用 Seatbelt 沙箱；无需虚拟机或容器。项目仍在开发，**尚未完整兼容 GEE，也未完成互联网多租户生产验收**。兼容范围及剩余差异见 [兼容文档](docs/gee-compatibility.md) 和 [目标](GOAL.md)。

## 功能与当前边界

- Python / GEE JavaScript 编辑、脚本保存与主动共享、持久任务队列、日志、取消及恢复。
- Python 同时保留 openEO `connection`，支持本地 `import ee; ee.Initialize()`、Map 和官方 Task 的受支持导出写法；不使用 Google 登录或 Drive 上传。用法与限制见 [语法文档](docs/syntax.md)。
- 本地数据目录、地图图层、色带与像素查询，GeoTIFF、NetCDF、CSV 本地导出。
- 数据集草稿/发布/下架、文件分块上传/续传、原件下载、GeoTIFF 入库与 COG 下载。
- 本地账号与角色、管理面板和操作记录；Keycloak OIDC、项目/数据集对象权限仍待实现。
- GEE 日期/集合/像素运算的明确子集；Join、数组/回归、分类器、LandTrendr、完整 GEE UI 等仍缺失。官方 API 签名存在不代表本地算法可用。

已有本机真实 Sentinel-2 小范围样本及多景独立基准验证，范围见 [验证说明](docs/verification.md)。本仓库**不含本机研究影像、账号、数据库、用户保存的脚本、分析结果、备份或原始审计日志**；新克隆默认没有研究数据。示例中的范围/日期仅用于匹配原验收样本，需先导入自己的数据。ERA5-Land 下载需另行配置 CDS 凭据和接受供应方条款。

## 从源码安装

需要原生 arm64 Python 3.11、Node.js 24、Homebrew、uv、Xcode Command Line Tools。Java 21 仅用于本项目，不要求修改全局 Java 默认版本。

```sh
git clone https://github.com/JamesLinYJ/local-ee.git
cd local-ee
HOMEBREW_NO_AUTO_UPDATE=1 brew install postgresql@17 openjdk@21 gdal udunits
uv sync --frozen
.venv/bin/python scripts/fetch_engine_dependencies.py
.venv/bin/python scripts/setup_native_engine.py
npm --prefix web ci
.venv/bin/python scripts/build_web.py
.venv/bin/python scripts/native.py start
```

访问 **http://localhost:8787/**。首次启动生成本机配置、原生数据库和管理员；凭据只写入 `deploy/native-login.txt`（0600），不得上传。数据和结果位于 `data/`，运行状态位于 `.native/`。大文件依赖按来源和 SHA-256 下载；上游快照如果被覆盖，校验会失败，应恢复已归档的匹配依赖并重新验收，不能绕过校验。

```sh
.venv/bin/python scripts/native.py status
.venv/bin/python scripts/native.py stop
```

也可使用根目录的 `启动工作台.command` / `停止工作台.command`。不会注册开机服务；关闭浏览器不会停止后台服务。API 仅监听回环地址，PostgreSQL 只使用私有 Unix socket。部署和隔离细节见 [原生部署](docs/native-macos.md)。

## 开发与检查

```sh
.venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run build
.venv/bin/python scripts/fetch_engine_dependencies.py --verify-only
```

GitHub Actions 执行便携组件检查。原生 Seatbelt 和实际 GeoTrellis/浏览器全流程需在目标 Mac 单独验收，不能用 CI 绿色替代。

| 目录 | 内容 |
| --- | --- |
| `gee/` | API、服务、权限、数据、EE 编译和原生任务调度 |
| `web/src/` | React 工作台、流程图与管理界面 |
| `runtimes/eejs/` | 离线官方 SDK 的脚本运行桥接 |
| `engine/` | GeoTrellis 适配、JNI 构建与依赖锁 |
| `vendor/` | 固定的第三方源码及原许可证；生成物排除 |
| `scripts/` / `tests/` | 构建、启停、验证、备份与回归 |
| `examples/` | Python / GEE JavaScript 示例 |
| `docs/` | 架构、部署、兼容、文件管理、外部连接与验证 |

`audit/` 的原始记录仅留本机；仓库只保留无凭据的定向编译检查程序。文档中历史审计路径指原部署上的证据，不随 Git 克隆。旧 Compose/Dockerfile 仅用于追溯，当前工程禁止重新创建虚拟机或容器，不把它们作为推荐启动方式。

## 文档

- [架构](docs/architecture.md)、[工程约束](AGENTS.md)、[兼容目标](GOAL.md)
- [语法参考](docs/syntax.md)、[影像数学](docs/gee-python/pixel-math.md)、[GEE 兼容矩阵](docs/gee-compatibility.md)、[991 项固定 API 清单](docs/gee-api-inventory.md)
- [原生部署](docs/native-macos.md)、[数据集文件](docs/dataset-files.md)
- [管理与认证组件](docs/admin-components.md)、[数据来源与连接](docs/data-connections.md)
- [验证范围](docs/verification.md)、[仓库与发布边界](docs/repository.md)
- [第三方来源和许可](THIRD_PARTY_NOTICES.md)、[上游版本](upstream-lock.json)

当前只面向受控本机使用；公网部署仍需独立完成身份、TLS、对象权限、容量和当前依赖组合的安全验收。
