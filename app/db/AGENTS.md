# 数据库模块约束

- PostgreSQL 结构变更必须新增递增的 `app/db/migrations/postgresql/Vxxx__*.sql` 文件。
- 新迁移使用 `IF NOT EXISTS` 等幂等写法；已执行的迁移文件不得修改，项目启动会自动执行未登记版本。
- 迁移 SQL 只维护 PostgreSQL。
- 数据库连接、迁移和诊断不得输出 `DATABASE_URL`、密码或其他凭据。
- 数据库异常只有在 SQLSTATE/异常类型明确对应现有错误规范时才包装；其他异常保留原始异常链和 traceback。
