# 数据库迁移（Alembic）

本目录是平台的数据库迁移机制。引入它是为了取代 `core/db/session.py` 里手写的运行时
DDL（`_run_compat_migrations`），把表结构变更纳入版本管理、可审查、可回滚。

## 首次接管（一次性）

### 已有库（生产 / 你当前的开发库，表已由旧 `init_db` 的 `create_all` 建好）
直接打基线，**不重复建表、零风险**：

```bash
alembic stamp head
```

之后这个库就归 Alembic 管了。

### 全新空库
一次性按当前模型建出全部表：

```bash
alembic upgrade head
```

## 日常：以后所有改表都走这里

1. 改 `core/db/models.py`（加字段 / 改类型 / 加索引等）。
2. 自动生成迁移：
   ```bash
   alembic revision --autogenerate -m "add xxx to yyy"
   ```
3. **务必人工 review** 生成的迁移文件（autogenerate 不是万能的，尤其 MySQL 方言、
   `LongText.with_variant` 这类变体、以及下面列的「尚未收编项」）。
4. 应用：`alembic upgrade head`；回滚上一步：`alembic downgrade -1`。

## 与 `_run_compat_migrations` 的关系（过渡期）

`core/db/session.py` 的 `_run_compat_migrations()` 暂时**保留不动**，它仍负责以下
Alembic 基线尚未覆盖的 MySQL 专属处理：

- 触发器型「部分唯一索引」：`user_model_configs.is_default_ukey`、`tools.global_name_ukey` /
  `tools.owner_name_ukey`；
- `uploads.data_url` / `uploads.text` 的 MEDIUMTEXT 加宽；
- 历史数据回填（从 PG 迁来时的若干 `UPDATE`）。

**后续计划**：把上述项逐条拆成显式 Alembic revision 收编，然后让 `init_db()` 在生产路径
只调 `alembic upgrade head`，彻底退役运行时 DDL。`init_db()` 当前仍被测试夹具和启动钩子使用，
故本次不改动其行为。

## 验证状态

- ✅ 离线已验证：`alembic history` / `alembic heads` 正常，基线 revision、env.py 模型注册
  （26 张表）、DATABASE_URL 注入均工作。
- ⏳ 在线往返（`upgrade` → `downgrade` → `upgrade`）需连到一个可写的 MySQL 库执行，
  建议在测试库 `lingshu_agent_test` 上先跑一遍确认。
