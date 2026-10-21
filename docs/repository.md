# 源码仓库与本机状态

GitHub 仓库为私有源码备份及后续开发入口。发布不改变现有本机数据、账号、任务或服务进程。

## 保留在 Git 中

- 自有源码、React 前端、示例、测试、架构与兼容目标。
- 固定第三方源码及许可证、Python/npm 依赖锁、JAR 来源/版本/校验清单。
- 构建/启停/迁移/备份程序，以及不含凭据的编译审查程序。

## 只保留本机

- `.env`、`.native/` 和 `deploy/*login*.txt`：数据库密码、会话配置、管理员凭据、运行锁和进程状态。
- `data/`：数据目录、原始文件、用户脚本任务与分析结果；`backups/` 和数据库转储。
- `audit/` 原件：可能包含账号/任务标识、机器路径、日志、浏览器截图、输出及安全扫描原文。
- Python/Node 环境、构建产物、缓存、原生库和大型 JAR；主机生成的 `deploy/*-lock.json`。

`.gitignore` 是默认排除规则，提交前仍须审查实际暂存内容。不要用 `git add -f` 把凭据、数据库、影像或审计原件加入历史。原件继续保留，不能为了仓库整洁删除用户研究数据。

## 依赖恢复

```sh
python3 scripts/fetch_engine_dependencies.py
python3 scripts/fetch_engine_dependencies.py --verify-only
```

下载仅在显式运行恢复程序时发生。程序核对 SHA-256 和字节数，不覆盖已有的不匹配文件；安全替代库的下载清单必须与 `engine/security-jar-lock.json` 一致。上游 GeoTrellis 使用快照地址，内容可能变化；哈希不符即失败，不能自动接受新字节。长期部署需要管理员在独立制品库保留匹配原件。GitHub 源码仓库本身不保证上游二进制永久可下载。

`vendor/` 保留原生构建依赖的源码；上游测试压缩包和本机生成物排除。该仓库不承诺运行所有上游仓库自身的完整测试，当前应用测试位于根目录 `tests/`。

## 版本与验收

`upstream-lock.json`、`uv.lock`、`web/package-lock.json`、`engine/*-lock.json` 是可共享的基线。`.native/engine-lock.json` 和 `deploy/native-lock.json` 由实际部署记录，可能含机器路径，仅留本机。

根项目暂未选择开源许可证；私有托管不产生额外开源授权。第三方许可证与版权声明按原样保留，见 `THIRD_PARTY_NOTICES.md`。
