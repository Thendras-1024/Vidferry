# SQLite 迁移至 PostgreSQL

本指南只用于已在旧版 Vidferry 中使用 SQLite 的部署。当前版本运行期只使用 PostgreSQL；迁移工具是一次性的离线导入，不会修改原始 SQLite 文件。

## 迁移前

1. 停止旧版和新版 Vidferry 后端，避免迁移期间仍有写入。
2. 将代码更新到包含 PostgreSQL 支持的版本，并按 [快速部署指南](../QUICK_DEPLOYMENT.md) 安装依赖。
3. 确认旧库路径。默认是 `db/database.db`；不要删除它。
4. 准备一个新的 PostgreSQL 数据库。目标库可以由 Vidferry 自动创建表，但其中不能有业务数据；不要将旧数据导入正在使用的数据库。

## 执行迁移

在项目根目录执行：

```powershell
conda activate vidferry
python scripts/prepare_local_env.py
docker compose --env-file .env -f docker-compose.postgres.yml up -d
python scripts/migrate_sqlite_to_postgresql.py preflight --sqlite db/database.db
python scripts/migrate_sqlite_to_postgresql.py migrate --sqlite db/database.db
```

`migrate` 会先验证 SQLite 完整性，再在 `db/backups/` 创建时间戳备份，随后自动初始化 PostgreSQL 表并导入数据。导入报告写入 `db/postgresql-migration-report.json`，其中包含每张源表的行数和校验摘要。

报告中的 `skippedTables` 会列出当前版本没有对应 PostgreSQL 表的旧表。它们不会被删除，但应在切换前确认是否包含需要保留的数据。

若旧 SQLite 文件不在默认位置，显式传入路径：

```powershell
python scripts/migrate_sqlite_to_postgresql.py migrate --sqlite D:/backup/vidferry/database.db
```

## 验证与启动

```powershell
python run.py
```

首次迁移到认证版本时，旧 SQLite 中没有 `auth_users` 表是正常情况。后端启动后，在另一个终端创建首个管理员：

```powershell
python -m app.auth.cli create-admin --username admin --display-name "管理员"
```

然后启动前端：

```powershell
cd sau_frontend
npm run dev
```

访问 `http://127.0.0.1:55173` 并登录。确认素材、视频线索、工作流和发布记录数量符合迁移报告后，再保留旧 SQLite 备份一段时间；不要在验证前删除原文件。

## 常见错误

- `PostgreSQL target table is not empty`：目标数据库已有业务数据。创建新的空数据库后重新迁移，不要直接覆盖数据。
- `runtime lock tables are not empty`：旧后端尚未干净停止。停止后端并等待运行中任务结束后重试。
- `DATABASE_URL must be configured`：先运行 `python scripts/prepare_local_env.py`，并确认 PostgreSQL 服务已启动。
- `only '%s', '%b', '%t' are allowed ...`：请更新到当前版本；该版本已处理旧 SQLite 文件扩展名查询中的 `%`。
