# SQLite 迁移至 PostgreSQL

本指南仅适用于旧版 Vidferry 的 SQLite 数据迁移。当前运行期只使用 PostgreSQL；迁移是一次性的离线导入，不会删除或修改原始 SQLite 文件。

## 迁移前检查

1. 停止旧版与新版后端，等待正在执行的下载、处理和发布任务结束。
2. 按 [快速部署](../QUICK_DEPLOYMENT.md) 安装当前版本依赖。
3. 确认旧库路径，默认是 `db/database.db`；先复制备份，且不要删除原文件。
4. 准备一个空 PostgreSQL 目标库。不要将迁移数据导入正在使用的业务库。

## 执行迁移

在项目根目录执行：

```powershell
conda run -n vidferry python scripts/prepare_local_env.py
docker compose --env-file .env -f docker-compose.postgres.yml up -d
conda run -n vidferry python scripts/migrate_sqlite_to_postgresql.py preflight --sqlite db/database.db
conda run -n vidferry python scripts/migrate_sqlite_to_postgresql.py migrate --sqlite db/database.db
```

`migrate` 会先检查 SQLite 完整性，再在 `db/backups/` 创建时间戳备份，初始化 PostgreSQL 表并导入数据。导入报告位于 `db/postgresql-migration-report.json`，包含源表行数、校验摘要和未映射表。

旧库不在默认目录时显式传入绝对路径：

```powershell
conda run -n vidferry python scripts/migrate_sqlite_to_postgresql.py migrate --sqlite D:/backup/vidferry/database.db
```

## 验证与切换

启动后端：

```powershell
conda run -n vidferry python run.py
```

首次迁移到认证版本时，旧 SQLite 没有 `auth_users` 表是正常情况。另开终端创建管理员：

```powershell
conda run -n vidferry python -m app.auth.cli create-admin --username admin --display-name "管理员"
```

再启动前端并登录 `http://127.0.0.1:55173`。核对素材、线索、工作流和发布记录数量与迁移报告一致后，保留 SQLite 原文件和备份一段时间；完成业务确认前不要删除它们。

## 常见错误

- `PostgreSQL target table is not empty`：目标数据库已有业务数据。创建新的空库后重试，不要覆盖现有库。
- `runtime lock tables are not empty`：旧后端没有干净停止。停止后端并等待运行任务结束后重试。
- `DATABASE_URL must be configured`：先运行准备脚本并确认 PostgreSQL 容器已启动。
- `only '%s', '%b', '%t' are allowed ...`：更新到当前 Vidferry 版本后重新执行预检。
