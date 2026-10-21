> 历史容器版本文档。当前原生版本请按 [macOS 原生部署](native-macos.md) 操作；不要运行这里的 Docker/Colima 命令。

# 备份与恢复

在工作台根目录执行 `python scripts/backup.py /独立磁盘/private-gee-backups`。脚本会拒绝正在运行或排队的任务，短暂停止 API/调度服务，生成 PostgreSQL 自定义格式转储和数据目录归档，然后恢复服务。归档权限为 600，含账号哈希、私有脚本、结果、数据库密码，不能公开分享。应使用独立磁盘或内部备份服务器保存；同盘备份仅用于恢复演练。

先停止数据同步：`docker-compose -f compose.yaml -f compose.sync.yaml stop sync`。备份脚本不会自动关闭所有独立任务容器，故运行前必须排空队列。定期检查备份文件可读，并实际恢复到单独实例。

恢复到**空的、新实例**：

1. 保留原实例，在新目录复制程序、固定版本清单和镜像；以新的 Compose 项目名与端口部署，避免覆盖原数据库。
2. 检查归档成员，无绝对路径、`..` 或符号链接后解压；恢复 `data/` 和配置。修正 `.env` 中 `HOST_DATA_ROOT` 为新目录的绝对路径。
3. 启动空 PostgreSQL：`docker-compose up -d db`。通过 `docker-compose exec -T db pg_restore -U gee -d gee --no-owner --no-acl --exit-on-error < database.dump` 导入。
4. 启动 API、worker、web。`--no-acl` 不导入旧实例的 GRANT/REVOKE，避免转储引用新实例尚不存在的 `gee_sync` 角色。需要同步时，待应用启动后执行 `python scripts/prepare_sync.py`，重新创建专用的非超级用户角色并仅授予目录表所需权限；不要为消除恢复错误手动创建超级用户或授予更宽权限。重启后不存在执行容器的 `running` 任务会明确失败，可重新提交；已经完成的结果由文件和数据库共同恢复。
5. 登录，读取一个私有脚本，下载已完成结果并与原 SHA256 比较，再提交小范围任务。

离线迁移镜像使用 `docker save ... -o images.tar` / `docker load -i images.tar`；文件较大。当前镜像名称和内容摘要在 `deploy/images-lock.json`，备份同时收录该文件和历史 `audit/images-lock.json`；历史锁仅作旧验收证据。更换 CPU 架构时应重新构建和验收对应架构镜像。

本轮 PostgreSQL 的 glibc 排序规则从 2.36 升级至 2.41，已执行重建索引和刷新排序规则版本。升级后的原数据库卷不可直接切回旧 glibc 数据库镜像。需要回退时，使用已留存的升级前备份 `work/security-backup/private-gee-20261021-131910.tar.gz`，按上述步骤恢复到空的、独立实例，并选用与该备份对应的镜像锁；不要在现有数据卷上降级。
