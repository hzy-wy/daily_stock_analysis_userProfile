# 多用户登录与权限体系：启用、验收和回滚指南

本文对应[多用户身份、登录与权限体系 PRD](multi-user-auth-rbac-prd.md)，用于把已经实现的 P0 多用户能力安全地启用到现有 DSA 部署。建议首次切换安排维护窗口，并完整执行本文的备份、迁移后检查和双用户隔离验收。

## 1. 当前可启用范围

当前版本已经提供：

- 本地用户名/邮箱标识 + Argon2id 密码；旧共享密码在升级后的首次成功登录时自动升级哈希。
- 普通工作台和管理后台两套独立登录入口、Cookie 和 Session audience。
- `platform_owner`、`platform_admin`、`auditor`、`member` 四类角色以及后端原子权限校验。
- 受信任终端创建首任 Owner、管理员一次性邀请、停用/启用账号、变更角色、审计日志、终端重置用户密码。
- 分析历史、回测、异步任务、Agent 对话、持仓、告警、决策信号、用量和 Web 自选股的用户级归属与查询隔离。
- 可配置的同工作台游客体验；不创建身份，仍可读取公开真实行情并使用不落库的临时 AI 问答，涉及个人数据的操作统一引导登录。
- 旧私有数据一次性归属首任 Owner；旧 `STOCK_LIST` 一次性复制为 Owner 的 Web 自选股。

以下仍属于 P1/P2，不应在本次启用时对外承诺：MFA、OIDC/企业 SSO、组织/团队空间、跨用户资源分享、API Key/服务账号登录、Bot 独立身份和 Desktop loopback 握手。Desktop 如果加载同一 Web 服务，现阶段沿用工作台登录页。

行情、公共基本面、汇率和结构化市场情报是共享数据；用户报告正文、会话、持仓等仍是私有数据。P0 不提供“管理员直接查看所有用户私有报告正文”的能力。

## 2. 角色与登录入口

| 角色 | 工作台 `/login` | 后台 `/admin/login` | 主要能力 |
| --- | --- | --- | --- |
| `platform_owner` | 是 | 是 | 全部权限；唯一且不可在后台停用或改角色 |
| `platform_admin` | 是 | 是 | 用户、配置、状态、审计和普通工作台能力 |
| `auditor` | 否 | 是 | 只读审计日志，不可管理用户或使用工作台 |
| `member` | 是 | 否 | 自己的分析、对话、持仓、告警、信号、回测和用量 |

同一浏览器可以同时保留工作台与后台登录：工作台使用 `dsa_app_sid`，后台使用 `dsa_admin_sid`。退出其中一个入口不会退出另一个入口，也不会影响其他设备。

游客体验没有独立页面，它不是账号、角色或认证 audience。访客从 `/login` 点击“进入游客体验”后进入正常工作台；公开真实行情与临时 AI 问答可用，持仓、自选保存、历史记录、告警等个人数据能力必须登录。

## 3. 上线前检查与备份

### 3.1 运行条件

- 推荐 Python 3.11；安装当前 `requirements.txt`，其中包含多用户密码所需的 `argon2-cffi`。
- 当前经过完整实现和回归验证的存储为项目默认 SQLite。
- Web/API 建议保持单服务进程。分析任务内部仍可通过 `MAX_WORKERS` 使用线程并发，但不要额外启动多个 Uvicorn worker：任务队列和 SSE 订阅状态当前是进程内状态。
- 公网必须使用 HTTPS，并让 Web 静态页面与 `/api` 保持同源。

### 3.2 停止写入

先停止 Web/API、定时分析器和其他可能写入同一数据库的进程。SQLite 备份期间不要运行分析、回测或持仓写入。

### 3.3 Windows PowerShell 备份示例

在项目根目录执行：

```powershell
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path (Resolve-Path '.').Path "backups/multi-user-$backupStamp"
New-Item -ItemType Directory -Force -Path $backupDir
if (Test-Path -LiteralPath '.env') { Copy-Item -LiteralPath '.env' -Destination $backupDir }
if (Test-Path -LiteralPath 'data/stock_analysis.db') { Copy-Item -LiteralPath 'data/stock_analysis.db' -Destination $backupDir }
if (Test-Path -LiteralPath 'data/.admin_password_hash') { Copy-Item -LiteralPath 'data/.admin_password_hash' -Destination $backupDir }
if (Test-Path -LiteralPath 'data/.session_secret') { Copy-Item -LiteralPath 'data/.session_secret' -Destination $backupDir }
Get-ChildItem -LiteralPath $backupDir
```

如果 `DATABASE_PATH` 指向其他位置，应备份该实际数据库及其同目录下的 `.admin_password_hash`、`.session_secret`，不要只复制示例路径。

### 3.4 Linux/macOS 备份示例

```bash
backup_stamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="backups/multi-user-${backup_stamp}"
mkdir -p "$backup_dir"
test ! -f .env || cp .env "$backup_dir/"
test ! -f data/stock_analysis.db || cp data/stock_analysis.db "$backup_dir/"
test ! -f data/.admin_password_hash || cp data/.admin_password_hash "$backup_dir/"
test ! -f data/.session_secret || cp data/.session_secret "$backup_dir/"
ls -la "$backup_dir"
```

## 4. 配置项

在 `.env` 中显式设置：

```dotenv
AUTH_MODE=multi_user
GUEST_ACCESS_ENABLED=false
GUEST_AI_REQUESTS_PER_HOUR=20
GUEST_AI_MAX_HISTORY_MESSAGES=10
DATABASE_PATH=./data/stock_analysis.db

# 普通工作台：最长 24 小时，空闲 8 小时
USER_SESSION_MAX_AGE_HOURS=24
USER_SESSION_IDLE_MINUTES=480

# 管理后台：最长 4 小时，空闲 30 分钟
ADMIN_SESSION_MAX_AGE_HOURS=4
ADMIN_SESSION_IDLE_MINUTES=30

# 直连或未严格控制代理头时必须保持 false
TRUST_X_FORWARDED_FOR=false

# 仅旧共享密码迁移时使用；这是迁移后的 Owner 登录名
MULTI_USER_LEGACY_OWNER_USERNAME=owner
```

规则说明：

- `AUTH_MODE` 一旦显式设置，就优先于旧 `ADMIN_AUTH_ENABLED`。无需为了 multi-user 再把旧开关设为 `true`。
- `GUEST_ACCESS_ENABLED=true` 在 `/login` 显示游客入口，并开放经过服务端白名单约束的公开行情与临时 AI 能力；默认 `false`。
- `GUEST_AI_REQUESTS_PER_HOUR` 限制单个来源 IP 每小时的游客 AI 请求数；`GUEST_AI_MAX_HISTORY_MESSAGES` 限制浏览器随请求携带的临时上下文条数。两项均不产生用户业务数据。
- 会话的“绝对有效期”和“空闲有效期”同时生效，以先到者为准；后台建议始终短于工作台。
- 只有当请求必定经过受控反向代理，且代理会清理并重写 `X-Forwarded-For`、`X-Forwarded-Proto`、`X-Forwarded-Host` 时，才可设置 `TRUST_X_FORWARDED_FOR=true`。
- 多用户模式不提供匿名网页初始化 Owner。首任 Owner 只能由服务器受信任终端创建或从旧凭据自动导入。

## 5. 三种启用路径

### 5.1 全新部署或从 `disabled` 启用

1. 安装后端依赖：

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. 如从源代码运行，构建 Web：

   ```powershell
   Set-Location apps/dsa-web
   npm ci
   npm run lint
   npm run build
   Set-Location ../..
   ```

3. 写入上一节的 `.env`，确保 `AUTH_MODE=multi_user`。
4. 在受信任终端创建首任 Owner；密码至少 12 位，输入时不会回显：

   ```powershell
   python -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"
   ```

5. 成功输出应类似：

   ```text
   Platform owner created: <user-id> (owner)
   ```

6. 启动服务：

   ```powershell
   python main.py --serve-only --host 127.0.0.1 --port 8000
   ```

   需要局域网直连时才改为 `0.0.0.0`，并先配置防火墙和 HTTPS 反向代理。

### 5.2 从旧共享密码 `legacy` 升级

1. 保留旧数据库和数据库目录内的 `.admin_password_hash`。
2. 设置 `AUTH_MODE=multi_user` 和期望的 `MULTI_USER_LEGACY_OWNER_USERNAME`。
3. 执行一次：

   ```powershell
   python -m src.auth bootstrap_owner --username owner
   ```

4. 初始化过程会先检测旧凭据并自动导入 Owner，因此正常情况下不会要求重新设置密码，而是输出已经存在的 Owner ID。
5. 使用 `MULTI_USER_LEGACY_OWNER_USERNAME` 与原共享密码登录。首次成功登录会把旧 PBKDF2 凭据升级为 Argon2id。
6. 核对旧报告、回测、对话、持仓、告警、信号和用量都只在 Owner 账号下可见；其他新用户默认看不到这些数据。

如果旧凭据文件损坏或格式无效，CLI 会转入全新 Owner 创建流程并要求输入至少 12 位的新密码。不要删除旧文件来“重试”，应先从备份确认原因。

### 5.3 已经存在 multi-user Owner

再次执行 `bootstrap_owner` 是幂等检查，不会覆盖 Owner 或询问新密码：

```powershell
python -m src.auth bootstrap_owner --username owner
```

预期输出：

```text
Platform owner is already available: <user-id>
```

## 6. Docker Compose 启用

1. 在宿主机项目根目录完成备份并更新 `.env`。
2. 构建新镜像：

   ```bash
   docker compose -f docker/docker-compose.yml build server
   ```

3. 初始化或检查 Owner。命令使用宿主机挂载的 `data/`，不会创建容器内临时数据库：

   ```bash
   docker compose -f docker/docker-compose.yml run --rm --no-deps -u dsa server \
     python -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"
   ```

4. 启动服务：

   ```bash
   docker compose -f docker/docker-compose.yml up -d server
   docker compose -f docker/docker-compose.yml logs --tail=200 server
   ```

5. 检查健康状态：

   ```bash
   curl -fsS http://127.0.0.1:8000/api/health
   curl -fsS http://127.0.0.1:8000/api/v1/auth/status
   ```

如果同时运行 `analyzer`，两者必须挂载同一个 `data/`，且备份/迁移阶段都应停止。不要用多个 `server` 副本承载当前进程内任务队列。

## 7. 数据库初始化和关联

首次执行 CLI 或启动后访问认证 API 时会自动执行：

1. 创建用户、身份、密码凭据、角色、权限、角色权限、用户角色、Session、邀请、API Key/服务账号预留、审计和安全事件表。
2. 给私有数据根增加 nullable `owner_user_id` 并建立索引。
3. 重建 SQLite 中旧的全局唯一约束，使对话摘要和回测汇总按 Owner 唯一。
4. 导入或创建首任 Owner，把旧私有根记录回填给该 Owner。
5. 通过外键或父记录关联继承子资源归属，例如回测结果继承分析历史、持仓事件继承持仓账户、告警触发继承告警规则。
6. 一次性将旧 `STOCK_LIST` 复制到 Owner 的 `user_watchlist_items`，迁移标记写入 `database_schema_migrations`，防止重复执行。

正常启动前可做只读表检查：

```powershell
python -c "from src.config import setup_env; setup_env(); import sqlite3, os; p=os.getenv('DATABASE_PATH','./data/stock_analysis.db'); c=sqlite3.connect(p); names={r[0] for r in c.execute('select name from sqlite_master where type=?', ('table',))}; required={'users','auth_identities','password_credentials','auth_sessions','roles','permissions','user_role_assignments','invitations','audit_logs','security_events'}; print('database=', p, 'missing=', sorted(required-names)); c.close()"
```

输出 `missing=[]` 才表示身份基础表齐全。不要手工修改 `owner_user_id` 或删除迁移记录。

## 8. 首次登录、邀请和账号运维

### 8.1 Owner 登录

- 工作台：`https://你的域名/login`
- 管理后台：`https://你的域名/admin/login`

先分别登录两个入口，然后确认退出后台后工作台仍保持登录；再重新登录后台。

### 8.2 邀请用户

1. 进入 `/admin/login`，使用 Owner 或 `platform_admin` 登录。
2. 在“邀请用户”输入新用户的登录名或邮箱标识，选择 `member`、`auditor` 或 `platform_admin`。
3. 生成的一次性令牌只展示一次。将它通过受信任渠道交给受邀者。
4. 受邀者打开 `/accept-invite`，粘贴令牌、设置显示名称和至少 12 位密码；也可使用：

   ```text
   https://你的域名/accept-invite?token=<一次性令牌>
   ```

5. 邀请默认 72 小时过期，接受后不能重复使用。

不要把邀请令牌写入 Issue、日志、截图或公开聊天。使用 URL 传递时，接受完成后应关闭该页面，避免浏览器历史长期保存令牌。

### 8.3 停用、启用和改角色

- 后台变更用户状态或角色后，该用户已有 Session 会被服务端吊销。
- 平台 Owner 不能被停用，Owner 角色也不能通过普通角色接口替换。
- `auditor` 只允许管理后台审计访问；如果需要使用工作台，应改为 `platform_admin` 或 `member`。

### 8.4 忘记密码

在受信任服务器终端执行，密码不会回显：

```powershell
python -m src.auth reset_user_password --username <登录名>
```

成功后该用户全部工作台和后台 Session 都会失效，并记录审计事件。

## 9. 反向代理和 Cookie 安全

推荐拓扑：

```text
浏览器 --HTTPS--> 受控反向代理 --HTTP/本机网络--> 单个 DSA Web/API 进程
```

必须满足：

- 静态 Web 与 `/api` 使用同一 scheme、host 和 port；当前 Cookie 登录不支持把 API 放到任意跨域域名。
- HTTPS 终止在反向代理时，代理应重写 `X-Forwarded-Proto=https`、`X-Forwarded-Host` 和 `X-Forwarded-For`，然后才设置 `TRUST_X_FORWARDED_FOR=true`。
- 不得把后端端口直接暴露公网，同时又信任客户端自行传入的 forwarded headers。
- 写请求会校验浏览器 `Origin` 与当前外部 Origin 一致；出现 `invalid_origin` 时优先检查代理协议和 Host 转发，不要关闭校验。
- 工作台和后台 Cookie 均为 `HttpOnly`、`SameSite=Lax`；通过 HTTPS 识别后自动增加 `Secure`。

## 10. 必做验收清单

建议使用两个浏览器配置文件或一个普通窗口加一个无痕窗口，分别登录 Owner 和 Member。

### 10.1 登录与权限

- [ ] 未登录访问工作台私有 API 返回 401。
- [ ] 若启用游客体验，未登录可从 `/login` 进入正常工作台，看到真实公开行情并完成临时 AI 问答。
- [ ] 游客刷新页面后 AI 会话消失，`conversation_messages`、`agent_provider_turns`、`llm_usage` 均无游客新增行；创建持仓账户、保存自选、查看私有历史等操作会提示登录，私有 API 仍返回 401。
- [ ] Owner 可以同时登录 `/login` 与 `/admin/login`。
- [ ] Member 能登录工作台，登录后台返回 403。
- [ ] Auditor 能登录后台并读取审计日志，不能管理用户，也不能登录工作台。
- [ ] 退出后台不影响同浏览器的工作台 Session。
- [ ] 停用或改角色后，目标用户的旧 Session 立即失效。
- [ ] 连续错误登录会返回 429；等待 5 分钟后恢复。

### 10.2 用户数据隔离

让 Owner 和 Member 分别创建不同内容，再交叉核对：

- [ ] 自选股列表不同，互不覆盖。
- [ ] 分别运行一只股票分析；历史记录、任务列表和 SSE 只出现自己的任务。
- [ ] 分别创建 Agent 会话；相同客户端 `session_id` 不会互相读取或覆盖摘要。
- [ ] 分别创建持仓账户、交易、现金流水和公司行动；“全部账户”视图只汇总自己的账户，修改 ID 也不能读取或写入对方子资源。
- [ ] 分别创建告警；规则、触发和通知结果只在所属用户下可见。
- [ ] 决策信号、信号后验、回测结果和汇总只计算本用户数据。
- [ ] `/usage` 只显示本用户调用用量。
- [ ] 公共行情、汇率和市场情报可以被不同用户共同读取。

### 10.3 运维

- [ ] `/api/health` 正常。
- [ ] 重启服务后数据库 Session 仍可按有效期恢复，任务队列中的运行中任务不作为可恢复状态承诺。
- [ ] 日志中没有数据库迁移失败、`bootstrap_required`、持续 `database is locked` 或 `invalid_origin`。
- [ ] 完成一次新备份，并记录启用时间、Owner 登录名和回滚备份位置；不要记录密码或邀请令牌。

## 11. 常见问题

### `503 bootstrap_required`

当前数据库没有活动 Owner，或进程读取了错误的 `DATABASE_PATH`。停止服务，确认 `.env` 与工作目录，再运行 `python -m src.auth bootstrap_owner --username owner`。

### CLI 提示 Owner 已存在

这是安全幂等行为，不会覆盖现有 Owner。若忘记密码，使用 `reset_user_password`，不要删除用户表或迁移记录。

### `legacy_identifier_conflict`

配置的 `MULTI_USER_LEGACY_OWNER_USERNAME` 已被非 Owner 账号占用。系统会拒绝自动提权；把该变量改为一个未使用的登录名后重新执行 bootstrap，不要手工把现有成员改成 Owner。

### 工作台已登录但后台仍要求登录

这是预期行为。两个入口的 Session 和 Cookie 故意隔离，需要在 `/admin/login` 单独登录。

### 返回 403 `invalid_origin`

检查浏览器访问地址、代理 `Host`、`X-Forwarded-Proto`、`X-Forwarded-Host` 和 `TRUST_X_FORWARDED_FOR` 是否匹配。不要通过伪造 Origin 或删除中间件绕过。

### 返回 429

同一登录名或同一客户端 IP 在 5 分钟内失败 5 次后触发限流；账号凭据也会临时锁定。排查错误密码或代理 IP 聚合问题，等待窗口结束再重试。

### 旧报告看不到

确认当前登录的是迁移后的首任 Owner，并检查启动进程实际使用的数据库路径。旧数据只回填给 Owner，不会复制给普通用户。

### SQLite 持续 locked

确认没有多个 server/analyzer 实例同时高频写同一数据库，备份程序没有长期占锁，数据库和 WAL 文件位于可靠本地磁盘。多实例高并发部署不是当前 SQLite P0 的认证范围。

## 12. 回滚

### 12.1 认证模式软回滚

发生登录 UI 或权限接入问题、但数据库迁移成功且数据完整时：

1. 停止所有进程。
2. 把 `.env` 中 `AUTH_MODE` 改为 `legacy`。如果是全新 multi-user 部署、此前没有旧共享密码，应在启动 Web 前从受信任终端执行 `python -m src.auth reset_password` 创建共享密码，避免把首次设密入口暴露给远程访问者。
3. 需要临时完全关闭认证时可改为 `disabled`，但绝不能在公网或不可信局域网使用。
4. 启动单个服务进程并验证旧入口。

软回滚不会删除身份表和 `owner_user_id`，后续可以再次切回 `multi_user`。

### 12.2 数据库完整回滚

仅在迁移失败、表结构异常或数据校验不一致时执行：

1. 停止所有会写数据库的进程。
2. 保留当前异常数据库副本用于排查。
3. 从第 3 节的维护窗口备份恢复数据库、`.env`、`.admin_password_hash` 和 `.session_secret`。
4. 将 `AUTH_MODE` 恢复为切换前模式，再启动并核对记录数。

不要在运行中覆盖 SQLite 文件，也不要只删除新身份表：私有记录已经带有归属和新唯一索引，局部删除会造成契约不一致。

## 13. 当前生产边界

本指南验证的是仓库默认 SQLite、单 Web/API 进程、同源 HTTPS/受控代理的 P0 私有多人部署。ORM 模型为 PostgreSQL 预留了部分索引条件，但现有增量迁移、SQLite 表重建、持仓写锁和整套集成测试尚未形成 PostgreSQL 生产认证；如要切换数据库或横向扩容，应单独设计 Alembic 迁移、共享任务队列、集中限流和分布式 SSE，再进行专项压测与故障演练。
