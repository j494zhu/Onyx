# Onyx — 部署交接 (本地 master → 服务器)

> 给服务器上的 agent。本文档描述本次本地改动、以及在服务器上需要执行/注意的事项。
> 前提:本地这批改动已 commit 并 push 到 `origin/master`。服务器追踪的也是 `master`。

---

## 0. 版本 / 分支

- 最新代码在 **`master`**,已推送到 GitHub `origin/master`。
- 服务器请用:
  ```bash
  git fetch origin && git reset --hard origin/master   # 或 git pull,确保工作区干净
  ```

---

## 1. 本次一共改了什么

### A. 功能改动(纯代码,随 git 过来)
1. **To-Do List**:从纯文本 `textarea` 改成**带 checkbox 的交互清单**,勾选状态持久化到后端。
2. **Data Visualization 配色**:Donut 每个扇区颜色按索引取自一组协调配色、**不重复**;Bar 全部用**同一种标准蓝**。
3. **图表刷新按钮**:Donut/Bar 切换的右侧加了一个刷新按钮,点击**无需刷新整页**即可重新拉取图表。
4. **暗色模式**:重画了 SVG 太阳/月亮图标;**自动跟随系统 `prefers-color-scheme`**;`<head>` 加了预绘制脚本,**深色刷新不再白闪**(主题 class 打在 `<html>` 上)。

### B. 数据库结构改动
- `user` 表**新增一列 `todos`**(`TEXT`,存 JSON 数组 `[{id,text,done}]`)。
- **不需要手动迁移**:app 启动时 `ensure_user_columns()` 会**幂等地** `ALTER TABLE "user" ADD COLUMN todos`(已处理多 worker 并发竞争,失败可容忍)。首次加载还会把旧的 `quick_note` 文本自动迁移成 todos。
- ⚠️ 这是**纯加列**,不动现有数据;旧数据不受影响。

### C. 安全 / 基础设施改动(**重点**)
1. **`docker-compose.yml`**(已被 git 跟踪 → 会随 `git pull` 自动更新,**无需手动复制**):
   - Redis 现在用 `--requirepass` 启动,**强制要求密码**;并加了带认证的 healthcheck。
   - web 的 `REDIS_URL` 改成 `redis://:${REDIS_PASSWORD}@redis:6379/0`(应用只读 `REDIS_URL`,单独的 `REDIS_PASSWORD` 变量它不读)。
   - `POSTGRES_PASSWORD` 与 `REDIS_PASSWORD` 改成 **fail-fast**:`${VAR:?... is required}`。**变量缺失时 `docker compose up` 会直接报错中止**,不再静默用 `change_me` 之类弱默认值。
2. **`.env`**(**未被 git 跟踪 → 不会随 git 过来,必须在服务器上手动处理!**):
   - 本地新增了 `REDIS_PASSWORD`,并把 `REDIS_URL` 改成带密码。
   - 本地**轮换了 `SECRET_KEY`**(旧的硬编码值曾出现在公开的 git 历史里 → 已泄露)。
   - 本地**换了 Postgres 密码**,并已对本地库执行过 `ALTER USER`。
   - 服务器有**自己的一套**密钥/密码,**不要用本地 `.env` 覆盖服务器 `.env`**。

---

## 2. 服务器上要做的事(按顺序)

### Step 1 — 拉最新代码
```bash
cd <项目目录>
git fetch origin && git reset --hard origin/master
```

### Step 2 — 手动更新服务器的 `.env`(`.env` 不在 git 里!)
**必须存在,否则新版 compose 会直接报错:**
- `REDIS_PASSWORD=<服务器自己的强随机值>`
- `REDIS_URL=redis://:<同上密码>@redis:6379/0`   ← 密码必须和 `REDIS_PASSWORD` **完全一致**
- `POSTGRES_PASSWORD=<见 Step 3>` 且 `DATABASE_URL` 里的密码与之一致
  - 注意 `DATABASE_URL` 的 host 应为 compose 服务名(本地是 `postgres`,按服务器 compose 实际服务名填)
- `SECRET_KEY=<新随机值>`(若服务器仍在用那个泄露过的旧 `SECRET_KEY`,**务必更换**;换了之后所有用户的登录会话会失效、需重新登录——这是正常的)
- 保留原有:`XAI_API_KEY`、`DEEPSEEK_API_KEY`、`POSTGRES_DB`、`POSTGRES_USER`、`REDIS_CHANNEL_PREFIX`、`SSE_HEARTBEAT_SECONDS=25`

生成随机值:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

校验 `.env` 一致性(不打印明文):
```bash
set -a; . ./.env; set +a
[ "$REDIS_PASSWORD" = "$(printf '%s' "$REDIS_URL" | sed -E 's#redis://:([^@]+)@.*#\1#')" ] && echo "REDIS ok" || echo "REDIS mismatch"
[ "$POSTGRES_PASSWORD" = "$(printf '%s' "$DATABASE_URL" | sed -E 's#.*://[^:]+:([^@]+)@.*#\1#')" ] && echo "PG ok" || echo "PG mismatch"
```

### Step 3 — 数据库密码(关键坑)
**改 `.env` 里的 `POSTGRES_PASSWORD` 不会改变已存在数据卷里的真实库密码**(Postgres 只在首次初始化空卷时用 `POSTGRES_PASSWORD`)。两种处理:

- **方案 A — 想换库密码(保数据,推荐)**:先进库把角色密码改成 `.env` 里的新值,再起服务。
  ```bash
  docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "ALTER USER <用户名> WITH PASSWORD '<.env 里的 POSTGRES_PASSWORD>';"
  ```
- **方案 B — 不想动库密码**:直接把 `.env` 的 `POSTGRES_PASSWORD` / `DATABASE_URL` **填成服务器库现有的密码**即可,不要 ALTER。

> Redis 密码**没有这个坑**:它无持久化的密码状态,重启即带上 `.env` 里的新密码。
> **绝对不要 `docker compose down -v`**——那会删卷、清空所有用户数据。

### Step 4 — 起服务
```bash
docker compose up -d --build
```
(`--build` 会用新代码重建镜像;app 启动时自动补 `todos` 列。)

### Step 5 — 验证(逐条应为 ✅)
```bash
set -a; . ./.env; set +a

# 1) 容器状态
docker compose ps

# 2) 新列已加上(schema 迁移成功)
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\d "user"' | grep -q todos \
  && echo "todos column ✅" || echo "todos column MISSING ❌"

# 3) web 能用配置里的密码连库
docker compose exec -T web python -c "import os,psycopg2; psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=5).close(); print('DB connect ✅')"

# 4) Redis 强制认证:无密码应失败
docker compose exec -T redis redis-cli ping 2>&1 | grep -qi NOAUTH \
  && echo "Redis requires auth ✅" || echo "Redis NOT protected ❌"

# 5) Redis 带密码应成功
docker compose exec -T -e RP="$REDIS_PASSWORD" redis sh -c 'redis-cli -a "$RP" ping' 2>/dev/null | grep -q PONG \
  && echo "Redis auth works ✅" || echo "Redis auth FAIL ❌"

# 6) 应用响应 + 日志无认证错误
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:5000/
docker compose logs web --since 5m 2>&1 | grep -iE "noauth|password authentication|operationalerror|traceback" || echo "logs clean ✅"
```
登录后实测:To-Do 勾选刷新后保留;图表刷新按钮可用;暗色模式切换正常。

---

## 3. 回滚
```bash
git reset --hard <上一个 commit>
docker compose up -d --build
```
- `todos` 列保留无害(旧代码不读它),数据不丢。

---

## 4. 易踩的坑速查
- **`docker compose up` 直接报 `... is required`** → 服务器 `.env` 缺 `REDIS_PASSWORD` 或 `POSTGRES_PASSWORD`,先补齐(Step 2)。
- **web 起来后连不上库 / `password authentication failed`** → `.env` 的库密码与库里真实密码不一致 → 走 Step 3(ALTER 或对齐 `.env`)。
- **千万别 `down -v`** → 清数据。
- **换了 `SECRET_KEY`** → 用户需重新登录(正常)。
- **`docker-compose.yml` 不用手动复制**(已跟踪,随 git 来);**`.env` 必须手动维护**(未跟踪)。
