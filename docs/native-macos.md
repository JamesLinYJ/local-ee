# macOS 原生部署

当前目标为 Apple Silicon macOS 原生运行，不使用 Docker、Colima、容器或虚拟机。Windows 虚拟机不属于本项目。用户已明确删除旧数据库；当前使用新建的本机数据库，不自动恢复旧账号、脚本或任务备份。影像、原始文件和历史结果文件仍在 `data/`；已有 STAC 文件已重新索引，来源不明确的旧 Sentinel-2 版本保持停用，合成验收数据集保持下架。

## 使用与启停

在项目根目录执行：

```sh
.venv/bin/python scripts/native.py start
.venv/bin/python scripts/native.py status
.venv/bin/python scripts/native.py stop
```

也可双击 `启动工作台.command` / `停止工作台.command`。访问 http://localhost:8787 。新管理员及密码在 `deploy/native-login.txt`，权限 0600。不要使用历史 `local-login.txt`。启动器不会注册登录项或系统常驻服务；启动后会常驻 PostgreSQL、一个 API worker 和调度器，退出时使用 `stop` 停止它们。关闭网页不等于停止服务。

| 组件 | 原生实现 | 持久位置 |
| --- | --- | --- |
| 网页和 API | Gunicorn，单 worker、4 个线程，同源静态资源；仅 127.0.0.1:8787 | `web/dist`、`.native/run/api.log` |
| 数据库 | PostgreSQL 17，32 MiB shared buffers、20 连接；只监听权限 0700 的 Unix socket，无 TCP 监听 | `.native/postgres`、`.native/run/pg` |
| 调度 | PostgreSQL 队列、advisory lock；同一时刻一个计算或入库任务，另有两个脚本槽位 | `gee/worker.py` |
| Python / JS | Python 3.11 / Node 24 + 官方 EE 客户端；独立 Seatbelt 进程 | `.native/eejs`、`data/jobs/<id>` |
| 科学引擎 | Java 21、Spark 4.0.4 local[1]、Scala 2.13、GeoTrellis、GDAL 3.13.3 | `.native/engine`、`.native/jars` |
| 文件与结果 | 原文件分块上传、标准化 COG、STAC、GeoTIFF/NetCDF/CSV | `data/uploads`、`data/assets`、`data/catalog`、`data/jobs` |

Spark 和 JVM 仅在计算时启动，完成、取消或超限后回收，不预留整台虚拟机的内存。一个 Spark JVM 的堆配置为 1 GiB；包括 Python/JVM 子进程的保守 RSS 合计上限为 4 GiB。脚本 RSS 上限 512 MiB，入库 2 GiB。RSS 按周期检查，属于进程树监督，不是 cgroups 的硬内存配额。

## Unix 沙箱与生命周期

`gee/native/sandbox.py` 生成 deny-default Seatbelt 规则，由 `/usr/bin/sandbox-exec` 在启动代码前应用。沙箱不存在、配置不合法或启动失败时任务失败，绝不回退到裸进程。

- Python/Node 只能读取运行库、桥接程序和本任务文件，只能写本任务临时目录；只能连接指定的回环 API 端口。不持有数据库或数据供应方凭据，不能读取其他任务、账号配置或任意用户文件。
- GeoTrellis 只读本机资产，可写本任务输出和临时目录；仅允许 Spark/Py4J 回环通信，禁止公网连接。`local[1]` 将 JAR 放入同一个 JVM 的 classpath，避免不必要的网络分发和 Darwin sendfile 权限。
- GeoTIFF 解析仅能读指定原件、写自己的输出，不允许网络。可信发布模块继续校验 SHA、类型、路径、波段、单位和任务状态。
- API 自身也在 Seatbelt 内运行，允许回环监听和数据库 Unix socket，禁止公网 TCP 出站；只读程序/网页/目录和任务数据，只能写上传区与私有临时目录。
- 已允许的公共系统文件包括时区、hosts/resolv.conf 和 LibreSSL 的系统配置文件；运行库只读路径不包括用户配置目录。`file-read-metadata` 允许路径元信息查询，不等于读取文件内容。
- 监督进程位于沙箱之外，环境不继承 DB/供应方凭据；通过专用管道收集有界日志，脱敏临时令牌。内核 rlimit 限制 CPU 时间、文件大小、打开文件、进程数；监督器还检查墙钟时间、进程树和 RSS。Spark/BLAS 线程数受配置约束，CPU 时间限制不等于严格的 CPU 百分比限额。
- 监督器与任务具有独立进程组。取消、超限和正常退出均回收整个任务进程组；控制状态放在脚本不可访问的 `.native/run/tasks`。调度器重启不会中断仍存活的监督器；进程 ID 与创建时间共同验证，拒绝向复用的 PID 发送信号。监督器丢失时按已验证子进程身份回收残留任务。

Seatbelt 和 `sandbox-exec` 依赖当前 macOS，属于本机部署边界。不能把 Unix 同一用户进程与 Linux 容器、独立系统账号或完整互联网多租户隔离视作等价；当前入口保持回环，团队对外上线仍需要单独的身份、TLS、配额和隔离验收。Python/JS SDK 与科学算法的兼容范围没有因此扩大，见 `gee-compatibility.md`。

## 初次构建与依赖

需要原生 arm64 Python 3.11、Node 24、Homebrew、Xcode Command Line Tools。不要配置 Rosetta 或 Linux VM。已安装 Java 21 时固定使用该版本，不修改用户的全局 Java 默认版本。

```sh
HOMEBREW_NO_AUTO_UPDATE=1 brew install postgresql@17 openjdk@21 gdal udunits
uv sync --frozen
.venv/bin/python scripts/fetch_engine_dependencies.py
.venv/bin/python scripts/setup_native_engine.py
npm --prefix web ci
.venv/bin/python scripts/build_web.py
.venv/bin/python scripts/native.py start
```

引擎单独使用 `.native/engine`，不破坏 API 的依赖锁。构建脚本在 `.native/sources` 复制上游源、调整必要的包元数据，编译 JEP 和 Darwin arm64 GDAL/JNI；上游仓库本身不改动。原始 JAR 被复制后移除实际旧版重复类并安装已锁定替代库，保留真实残余风险，不删除漏洞元数据制造“干净”报告。首轮执行会生成 `.native/engine-lock.json`、`.native/engine-requirements.lock`、`.native/jar-hardening.json`；部署摘要见 `deploy/native-lock.json`。

本机使用完整 Homebrew GDAL，其编译驱动和原生依赖与原 Linux 最小化 GDAL 不同。输入仍强制 GTiff、限制解码尺寸、隔离网络和路径；新依赖组合尚不能援引历史容器安全扫描作为当前扫描结果。已知第三方残余风险和完整生产审计继续保持未完成状态。

Git 克隆不包含 JAR、影像、数据库或凭据。依赖恢复程序核对来源清单及 SHA-256，匹配本机已有文件时不重复下载；上游快照变更会明确失败。仓库边界见 [repository.md](repository.md)，历史验证摘要见 [verification.md](verification.md)。

## 备份与独立恢复校验

```sh
.venv/bin/python scripts/backup.py /绝对路径/备份目录
.venv/bin/python scripts/verify_backup.py /绝对路径/备份.tar.gz --report /新的绝对路径/恢复报告.json
```

备份要求没有排队或运行任务，暂时停止 API/调度以冻结写入，使用原生 pg_dump，打包数据库、原始数据/结果、当前配置和依赖锁；完成后恢复原先运行的服务。文件权限为 0600，包含凭据，需由管理员妥善保管。校验器在现有本机 PG 中创建随机命名的临时数据库，恢复并核对各表行数、备份内全部数据文件 SHA，最后只删除其创建的临时数据库。此校验不覆盖独立备份设备故障。

旧数据库已经删除；保留的历史归档不会自动导入当前实例。若需恢复某个版本，先停止业务，使用全新目标库及显式恢复操作，不向现用数据库直接覆盖恢复。

## 验证证据

- `audit/native-macos-multiscene-v5/validation.json`：23 项多景/毫秒日期/归约/掩膜/表达式输出与独立 NumPy 基准比较。
- `audit/native-macos-real-v3/engine-integration.json`、`export-values.json`：真实 Sentinel-2 NDVI、NDWI、GeoTIFF、NetCDF、CSV、空查询与导出数值。
- `audit/native-macos-live-v2/validation.json`：12 项真实 HTTP/原生进程控制，包括调度器重启、取消、错误脚本、凭据/文件/网络拒绝、令牌脱敏与撤销、上传/入库/COG 下载。
- `audit/native-macos-live-v2/resources.json`：空闲 RSS 合计 352.4 MiB；短时 CPU 样本仅供本机参考，RSS 含共享页重复计数。
- `audit/native-macos-live-v2/backup-restore-final.json`：独立临时数据库恢复、行数及备份内 646 个文件 SHA 核对；`workbench.png` 为 Edge 真实 GEE NDVI 地图和导出完成界面。
- `audit/native-macos-download-v1/validation.json`：经用户明确授权本站多文件下载后，Edge 实际下载 GeoTIFF，SHA256 与任务输出一致；45590 个有效像素，掩膜差异 0，独立 NDVI 基准最大绝对误差 1.7881393432617188e-7，满足 1e-6 容差。

以上是本机算法/运行验证，不是与 Google 专有服务的同数据对照，也不等于完成全部生产验收。历史 `audit/native-macos-*-v1..v4` 中失败尝试保留，不覆盖成成功报告。
