> 历史容器版本文档。当前原生版本请按 [macOS 原生部署](native-macos.md) 操作；不要运行这里的 Docker/Colima 命令。

# 部署与版本

## 已部署环境

macOS Apple Silicon；Colima 专用 profile `private-gee`，8 vCPU / 24 GiB 内存 / 100 GiB 虚拟磁盘。计算任务默认 6 CPU / 10 GiB / 1800 秒，同时一个；Python 运行器 1 CPU / 512 MiB / 120 秒，同时两个。重任务排队、状态和数据快照由 PostgreSQL 持久化。这个小样本测试不能推算全球目录或 4 TB 数据的性能。

API、调度器、数据库和脚本使用 Docker 内部网络；重计算容器 `network=none`。仅 nginx 绑定主机回环端口。worker 持有 Docker socket，因此它和宿主机管理员是可信边界；脚本容器不持有该 socket、数据库密码、供应方凭据或数据目录。

## 重新构建

需要 Docker/Compose、Node 22.12+（本机 Node 24）/npm、Python 3.11/uv。初次构建会访问系统包、Python、npm 和容器镜像仓库，不属于离线分析运行。保留 vendor、JAR 及锁文件。`.env` 已存在时 `scripts/configure.py` 会拒绝覆盖。

```sh
python3 scripts/configure.py   # 仅新部署执行
uv sync --frozen
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web test
python3 scripts/build_web.py
DOCKER_CONTEXT=colima-private-gee docker build -f deploy/Dockerfile -t private-gee-app:security .
DOCKER_CONTEXT=colima-private-gee docker build -f engine/Dockerfile -t private-gee-engine:security .
DOCKER_CONTEXT=colima-private-gee docker build -f deploy/Dockerfile.nginx -t private-gee-nginx:security .
DOCKER_CONTEXT=colima-private-gee docker build -f deploy/Dockerfile.postgres -t private-gee-postgres:security .
DOCKER_CONTEXT=colima-private-gee docker build -f runtimes/eejs/Dockerfile -t private-gee-js:local .
DOCKER_CONTEXT=colima-private-gee python3 scripts/pin_images.py --image APP_IMAGE=private-gee-app:security --image ENGINE_IMAGE=private-gee-engine:security --image POSTGRES_IMAGE=private-gee-postgres:security --image NGINX_IMAGE=private-gee-nginx:security --image JS_IMAGE=private-gee-js:local
DOCKER_CONTEXT=colima-private-gee docker-compose up -d --no-build
```

ARM 镜像包含 Python 3.11、Java 21、Spark 4.0.4 / Scala 2.13、GeoPySpark 0.4.10+openeo 和 GeoTrellis extensions 2.6.4 快照。JEP 4.1.1、GDAL 3.13.3、Rasterio 1.3.11 和 gdal-warp JNI 在 ARM 上编译。GeoPySpark 的旧 protobuf 生成代码使用 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` 兼容 protobuf 5.29.6。当前镜像 ID 以 `deploy/images-lock.json` 为准；运行镜像含 `/opt/python-freeze.txt` 和 `/opt/jars-built.sha256`。`audit/` 是早期验收材料。

`engine/patch_gdal_jni.py` 将元数据指针贯穿 JNI 接口声明为 const，适配 GDAL 3.13。C++17 构建时显式包含 utility，补足上游源码缺失的标准头。`engine/config.py` 关闭远程 ETL、外部作业注册、Vault 和 OpenSearch；OpenTelemetry 导出关闭。

运行用 `.env` 固定镜像内容 ID；本地构建镜像没有公共仓库地址，跨机器需 `docker save/load`。构建仍使用动态 apt 仓库，部分上游 Python 依赖在构建时解析，因此目前不是逐字节可复现构建。构建出的完整版本清单和内容 ID 可以固定部署行为。上游 extensions JAR 的 manifest 标记 `d240b43-dirty`，保留原件及 SHA256；不能称其等同于纯净提交的可复现产物。

该 Dockerfile 可作为其他 Linux 架构移植起点；本次仅实际构建、运行 ARM64，不声称 amd64 也已验收。

## 前端

交付源码 `web/` 使用 TypeScript strict + React。CodeMirror 6、OpenLayers、Motion 和 React Flow 均打包为同源静态资源，流程图按需加载；运行时不从 CDN 拉取库或字体。`scripts/build_web.py` 在临时目录编译，先发布资源、最后切换 index，保留旧资源哈希供已打开页面使用。`deploy/web-lock.json` 记录实际前端文件校验和。旧 Vue 工程已移到任务工作区备份。

## 本地账号

```sh
DOCKER_CONTEXT=colima-private-gee docker-compose exec api python -m gee.admin user 用户名
```

按终端提示输入至少 12 位密码。对已有用户名执行会更新密码并撤销旧会话。勿把密码写进命令参数或聊天。验收账号以 `audit_` 开头，不用于日常工作。

## 同步

当前同步服务关闭，已有数据可以离线分析。配置 `deploy/sync.yaml` 中研究区、日期、启用来源后，管理员可手动运行：

```sh
DOCKER_CONTEXT=colima-private-gee python3 scripts/prepare_sync.py
DOCKER_CONTEXT=colima-private-gee docker-compose -f compose.yaml -f compose.sync.yaml up -d egress
DOCKER_CONTEXT=colima-private-gee docker-compose -f compose.yaml -f compose.sync.yaml run --rm sync python -m gee.sync --once
```

需要定时同步时启动 `sync` 服务，每 24 小时检查一次；结束日期设为 `today` 才会自动扩大时间范围。同步的日期区间含结束日，openEO 查询区间不含结束点。CDS 凭据仅放在同步服务配置中，不进入分析容器。

任务文件和数据库需要共同备份。当前未实施每用户磁盘硬配额，大区域同步限制为单景 400 万像素；管理员仍须监控可用空间。

安全构建移除聚合 JAR 中被替换的真实类，并使用 `engine/security-jar-lock.json` 校验替代库。新镜像固定记录在 `deploy/images-lock.json`；`audit/` 保留原验收记录。PostgreSQL 从 glibc 2.36 切换到 2.41 时，先备份并停应用，再 `REINDEX DATABASE gee`，最后 `ALTER DATABASE gee REFRESH COLLATION VERSION`。数据库镜像以 postgres UID 999 运行，不再保留 gosu。

同步使用专用 `gee_sync` 角色，仅授予 collections/items/sync_runs 读、插入和更新；仅挂载 assets/catalog/raw，不挂载 jobs。外部光学读取强制 GTiff；JSON 8MiB、1000页、单文件下载512MiB、单来源输出2GiB、输出盘低水位1GiB，并设置容器资源限额。这些限制会明确中止超限同步；仍不等于永久磁盘配额或已完成所有来源的实际验收。
