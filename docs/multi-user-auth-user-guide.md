# 多用户账号与登录统一使用说明

本文是 DSA 私有多人部署的日常使用手册，整合首次启用、角色划分、邀请码开户、登录/注册/游客入口、账号管理、数据隔离、排障和回滚。产品设计与数据库细节见[多用户身份、登录与权限体系 PRD](multi-user-auth-rbac-prd.md)，生产上线的完整备份和代理配置见[多用户登录与权限启用指南](multi-user-auth-deployment-guide.md)。

> 当前支持边界：SQLite、单 Web/API 进程、Web 与 API 同源。公网部署必须使用 HTTPS 和受控反向代理。

## 一、请保存的三个网址与一个登录页入口

本地默认地址如下：

| 用途 | 本地入口 | 谁使用 |
| --- | --- | --- |
| 产品工作台登录 | [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) | `platform_owner`、`platform_admin`、`member` |
| 管理后台登录 | [http://127.0.0.1:8000/admin/login](http://127.0.0.1:8000/admin/login) | `platform_owner`、`platform_admin`、`auditor` |
| 邀请码注册 | [http://127.0.0.1:8000/accept-invite](http://127.0.0.1:8000/accept-invite) | 尚未开户的受邀者 |
| 游客体验 | [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) 后点击“进入游客体验” | 暂不开户的体验者；需启用 `GUEST_ACCESS_ENABLED` |

如果服务端口不是 `8000`，把地址中的端口替换为实际 `WEBUI_PORT` 或 `--port`。部署到服务器后，把 `http://127.0.0.1:8000` 替换为实际 HTTPS 域名，例如：

```text
https://stock.example.com/login
https://stock.example.com/admin/login
https://stock.example.com/accept-invite
```

`127.0.0.1` 只代表访问者自己的电脑。远程用户不能用自己电脑上的 `127.0.0.1` 访问服务器，必须使用服务器域名或允许访问的局域网地址。

### 1.1 游客体验不是游客账号

游客点击登录页入口后直接进入与正式用户相同的 `/` 工作台，不存在单独的 Demo 页面，也不会创建用户、认证 Cookie 或服务端 Session。游客可以读取真实公开行情、使用行情筛选，并在同一 AI 问股界面进行即时对话。

游客 AI 对话不会写入 `conversation_messages`、`agent_provider_turns` 或 `llm_usage`，浏览器只把有限的当前页面消息随下一次请求临时传给服务端；刷新页面或退出游客模式后即清空。服务端为游客 AI 使用单独的公开工具白名单，不能读取用户历史报告、持仓或回测数据。

这里的“不产生实际数据”特指不创建游客身份和用户业务记录；读取真实行情时，数据供应商缓存、AlphaSift 公共行情缓存与必要运行日志仍可能正常更新，它们不归属于某个游客账号。

当游客尝试新建持仓账户、保存自选、生成正式分析/复盘报告、查看 AI 建议历史、设置预警或执行其他个人数据操作时，页面会弹出登录/邀请码注册提示，后端仍返回 `401`，不会依赖前端按钮隐藏来保证安全。

### 1.2 给身边朋友体验时怎么分享

1. 在 `.env` 中设置 `GUEST_ACCESS_ENABLED=true`，并配置 `GUEST_AI_REQUESTS_PER_HOUR` 与 `GUEST_AI_MAX_HISTORY_MESSAGES`。
2. 执行 Web 构建并完整重启 Web/API 服务。
3. 仅在服务器本机体验时，打开 `http://127.0.0.1:8000/login` 并点击“进入游客体验”。
4. 同一局域网分享时，服务需要监听 `0.0.0.0`，然后把 `http://<服务器局域网IP>:8000/login` 发给朋友；Windows 防火墙只对“专用网络”开放所需端口。
5. 跨公网分享时使用 HTTPS 域名和受控反向代理，不要把 `127.0.0.1` 发给远程用户。
6. 体验结束后将开关改回 `false` 并重启服务，登录页游客入口会关闭，已打开页面的后续匿名 API 调用也会被拒绝。

局域网启动示例：

```powershell
.\.venv\Scripts\python.exe main.py --serve-only --host 0.0.0.0 --port 8000
```

游客模式会读取真实公开行情并消耗真实模型额度。它适合受控的小范围体验，不是防滥用的公开 SaaS 方案；公网开放时必须使用 HTTPS、反向代理限流和明确的成本监控。

## 二、用户群体和四个系统角色

产品层面可理解为普通用户、审计员、平台管理员三类使用人群；代码中另有唯一的首任 Owner，因此实际存在四个角色：

| 角色 | 中文定位 | 工作台 `/login` | 后台 `/admin/login` | 账号来源 | 核心权限 |
| --- | --- | --- | --- | --- | --- |
| `platform_owner` | 首任平台所有者 | 可以 | 可以 | 仅受信任终端创建，系统唯一 | 全部平台权限；不可在后台停用或改为其他角色 |
| `platform_admin` | 平台管理员 | 可以 | 可以 | Owner/Admin 邀请 | 管理用户、邀请、配置、状态和审计，也可使用工作台 |
| `auditor` | 审计员 | 不可以 | 可以 | Owner/Admin 邀请 | 只读审计日志；不能管理用户或使用产品工作台 |
| `member` | 普通用户 | 可以 | 不可以 | Owner/Admin 邀请 | 使用自己的分析、Agent、持仓、告警、信号、回测、自选股和用量 |

关键规则：

- 系统只有一个 `platform_owner`，任何人都不能通过网页创建第二个 Owner。
- 后台不能把普通账号升级为 Owner，也不能停用或降级首任 Owner。
- Owner 和 `platform_admin` 都可以邀请 `member`、`auditor`、`platform_admin`。
- 系统不提供公开自由注册；没有邀请码的访问者不能自行开户。
- 游客不是系统角色；它是同一工作台中的匿名状态，只能访问公开行情和无持久化 AI 能力，不能进入管理后台或访问任何用户私有资源。

## 三、完整账号生命周期

```text
服务器受信任终端创建唯一 Owner
            ↓
Owner 登录管理后台
            ↓
Owner/Admin 选择角色并创建一次性邀请码
            ↓
受邀者在邀请码注册页面设置显示名称和密码
            ↓
根据角色进入工作台或管理后台
```

邀请码默认 72 小时过期，只能成功使用一次。令牌只在创建时展示一次，不要写入 Issue、日志、公开聊天或长期截图。

## 四、首次启用多用户模式

以下命令在项目根目录执行。Windows 下建议始终显式使用项目 `.venv`，避免误用 Anaconda `base` 环境。

### 4.1 停止写入并备份

先停止 Web、定时分析器和所有可能写入同一数据库的进程，然后备份：

```text
.env
data/stock_analysis.db
data/.admin_password_hash
data/.session_secret
```

如果 `.env` 中 `DATABASE_PATH` 指向其他位置，应备份实际数据库及其认证文件。

### 4.2 检查 `.env`

至少需要：

```dotenv
AUTH_MODE=multi_user
GUEST_ACCESS_ENABLED=true
GUEST_AI_REQUESTS_PER_HOUR=20
GUEST_AI_MAX_HISTORY_MESSAGES=10
DATABASE_PATH=./data/stock_analysis.db

USER_SESSION_MAX_AGE_HOURS=24
USER_SESSION_IDLE_MINUTES=480

ADMIN_SESSION_MAX_AGE_HOURS=4
ADMIN_SESSION_IDLE_MINUTES=30

TRUST_X_FORWARDED_FOR=false
MULTI_USER_LEGACY_OWNER_USERNAME=owner
```

说明：

- 显式设置的 `AUTH_MODE=multi_user` 优先于旧 `ADMIN_AUTH_ENABLED`。
- `GUEST_ACCESS_ENABLED=true` 时在工作台登录页显示“进入游客体验”，并开放严格的匿名 API 白名单；没有独立 `/demo` 路由。
- `GUEST_AI_REQUESTS_PER_HOUR` 是每个来源 IP 的进程内小时限额，由 AI 问股、AI 选股和热点智能详情共享；限额计数不写数据库，服务重启后清空。多 Worker 场景不会共享计数，因此当前仍要求单 Web/API 进程。
- `GUEST_AI_MAX_HISTORY_MESSAGES` 限制每次游客问股随请求携带的临时上下文，默认 `10`，服务端最大允许 `30`。
- 本机直连时保持 `TRUST_X_FORWARDED_FOR=false`。
- 只有受控反向代理会清理并重写 forwarded headers 时，才可以考虑改为 `true`。

检查程序是否成功读取配置：

```powershell
.\.venv\Scripts\python.exe -c "from src.config import setup_env; setup_env(); import os; print(os.getenv('AUTH_MODE'))"
```

应输出：

```text
multi_user
```

### 4.3 安装依赖并构建 Web

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Set-Location apps/dsa-web
npm ci
npm run lint
npm run build
Set-Location ../..
```

### 4.4 创建唯一的首任 Owner

```powershell
.\.venv\Scripts\python.exe -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"
```

新密码至少 12 位，终端输入时不会回显。成功输出类似：

```text
Platform owner created: <user-id> (owner)
```

再次执行命令只做幂等检查，不会覆盖 Owner 或重新询问密码：

```text
Platform owner is already available: <user-id>
```

如果是旧共享密码升级，系统会导入旧凭据作为 Owner；使用原共享密码首次登录后，密码哈希会自动升级为 Argon2id。

### 4.5 启动服务

```powershell
.\.venv\Scripts\python.exe main.py --serve-only --host 127.0.0.1 --port 8000
```

看到服务启动成功后，先打开：

1. [工作台登录](http://127.0.0.1:8000/login)
2. [管理后台登录](http://127.0.0.1:8000/admin/login)

Owner 应分别登录一次两个入口，确认都可正常进入。

## 五、Owner 或管理员邀请用户

1. 打开[管理后台登录](http://127.0.0.1:8000/admin/login)。
2. 使用 Owner 或 `platform_admin` 的账号密码登录。
3. 在邀请区域填写受邀者登录名或邮箱标识。
4. 选择受邀角色：
   - 普通用户：`member`
   - 审计员：`auditor`
   - 平台管理员：`platform_admin`
5. 创建邀请并立即复制一次性令牌。
6. 通过可信私密渠道把令牌和[邀请码注册入口](http://127.0.0.1:8000/accept-invite)交给受邀者。

也可以把令牌放入注册地址，方便受邀者打开：

```text
http://127.0.0.1:8000/accept-invite?token=<一次性令牌>
```

生产环境应使用实际 HTTPS 域名。URL 可能保留在浏览器历史中，注册完成后建议关闭页面并删除包含令牌的临时消息。

## 六、受邀者注册账号

1. 打开[邀请码注册页面](http://127.0.0.1:8000/accept-invite)。
2. 输入或确认邀请码。
3. 填写显示名称。
4. 设置不少于 12 位的密码并再次确认。
5. 提交后完成账号创建。
6. 邀请成功使用后立即失效，不能再次注册。

如果提示邀请无效，应让 Owner/Admin 检查邀请是否已过期、已接受或已撤销，然后重新创建邀请；不要反复使用旧令牌。

## 七、注册后从哪里登录

- `member`：进入[产品工作台登录](http://127.0.0.1:8000/login)。
- `auditor`：进入[管理后台登录](http://127.0.0.1:8000/admin/login)。
- `platform_admin`：两个入口都可以登录，但两个入口需要分别登录。
- `platform_owner`：两个入口都可以登录，但两个入口需要分别登录。

工作台和后台使用两套独立 Cookie：

```text
工作台：dsa_app_sid
管理后台：dsa_admin_sid
```

因此，同一浏览器可以同时保留两种会话；退出后台不会退出工作台，退出工作台也不会退出后台，其他设备上的 Session 同样不受单次退出影响。

## 八、管理员的日常账号操作

Owner 或 `platform_admin` 可以：

- 查看用户列表。
- 创建新的邀请。
- 将普通账号设置为启用或停用。
- 在 `member`、`auditor`、`platform_admin` 之间调整角色。
- 查看权限允许范围内的审计日志。

停用账号或改变角色后，该用户现有工作台和后台 Session 会被服务端吊销，需要按新权限重新登录。

首任 Owner 受到额外保护：不能在后台停用、删除、降级或替换角色。

## 九、用户忘记密码

当前 P0 不提供公开的邮件找回密码。管理员应在服务器受信任终端执行：

```powershell
.\.venv\Scripts\python.exe -m src.auth reset_user_password --username <登录名>
```

设置成功后，该用户所有现有工作台和后台 Session 都会失效，并记录安全审计事件。

旧共享密码模式使用的是另一条命令：

```powershell
.\.venv\Scripts\python.exe -m src.auth reset_password
```

不要在 `multi_user` 模式下混用旧共享密码重置命令。

## 十、数据隔离规则

以下数据按当前登录用户隔离：

- Web 自选股
- 分析历史、异步任务和 SSE 状态
- Agent 会话、摘要和流取消
- 持仓账户、交易、现金流水和公司行动
- 告警规则、触发记录和通知结果
- 决策信号、后验和反馈
- 回测结果和汇总
- LLM 用量

以下属于共享公共数据：

- 行情和交易日数据
- 公共基本面与汇率
- 结构化市场情报

P0 不提供“管理员直接查看所有用户私有报告正文”的能力。管理员权限不等于绕过资源归属。

## 十一、首次启用后的验收

建议准备两个浏览器配置文件，分别登录 Owner 和 Member：

- [ ] Owner 可以分别登录工作台和后台。
- [ ] 在 `/login` 点击“进入游客体验”后进入正常 `/` 工作台，市场看板显示真实公开行情。
- [ ] 游客 AI 问股可以返回真实行情分析，但刷新页面后对话消失，`conversation_messages`、`agent_provider_turns`、`llm_usage` 均没有游客新增记录。
- [ ] 游客提交“新建持仓账户”、保存自选或生成正式报告时出现登录/邀请码注册弹窗，数据库没有新增个人业务记录。
- [ ] Member 可以登录工作台，但不能登录后台。
- [ ] Auditor 可以登录后台读取审计，但不能登录工作台或管理用户。
- [ ] 退出后台后，同一浏览器的工作台仍保持登录。
- [ ] 停用或改角色后，目标用户旧 Session 立即失效。
- [ ] Owner 和 Member 的自选股、历史、任务、Agent、持仓、告警、信号、回测和用量互不可见。
- [ ] 两个用户都可以读取公共行情和市场数据。
- [ ] 服务日志中没有持续出现 `bootstrap_required`、`database is locked` 或 `invalid_origin`。

## 十二、常见报错

### 12.1 `cannot import name 'InvalidHashError'`

原因通常是终端仍在使用 Anaconda `base` 的旧 `argon2-cffi`，而不是项目 `.venv`。使用：

```powershell
.\.venv\Scripts\python.exe -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"
```

### 12.2 `set AUTH_MODE=multi_user before bootstrapping an owner`

原因是 `.env` 没有有效的 `AUTH_MODE=multi_user`，或者该行前面仍有 `#`。修改 `.env` 后用第 4.2 节命令检查实际读取值。

### 12.3 `503 bootstrap_required`

当前数据库没有有效 Owner，或服务读取了错误的 `DATABASE_PATH`。停止服务，确认工作目录和 `.env`，再从受信任终端执行 Owner 初始化命令。

### 12.4 `legacy_identifier_conflict`

旧 Owner 导入所使用的 `MULTI_USER_LEGACY_OWNER_USERNAME` 已被普通账号占用。系统会拒绝自动提权；应改成未使用的登录名后重新初始化，不能手工把现有 Member 改为 Owner。

### 12.5 工作台登录后，后台仍要求登录

这是预期行为。两个入口使用不同 audience 和 Cookie，必须分别登录。

### 12.6 `403 invalid_origin`

浏览器访问地址与服务识别到的外部 Origin 不一致。检查代理的 `Host`、`X-Forwarded-Proto`、`X-Forwarded-Host` 和 `TRUST_X_FORWARDED_FOR`，不要关闭 Origin 校验绕过问题。

### 12.7 `429` 登录受限

同一登录名或同一客户端 IP 在 5 分钟内连续失败 5 次会触发限流。确认密码和代理 IP 配置后等待窗口结束。

### 12.8 登录页没有“进入游客体验”

确认 `.env` 中存在 `GUEST_ACCESS_ENABLED=true`，然后完整重启 Web/API 服务。该配置由服务端认证状态接口读取，仅刷新浏览器或只重新构建前端不会改变运行中的服务端环境。

## 十三、备份与回滚摘要

启用前应在停止所有写入后备份数据库、`.env`、`.admin_password_hash` 和 `.session_secret`。

认证入口需要临时回滚时：

1. 停止所有进程。
2. 把 `AUTH_MODE` 改为 `legacy`。
3. 全新 multi-user 部署如果从未创建旧共享密码，应先从受信任终端执行 `.\.venv\Scripts\python.exe -m src.auth reset_password`。
4. 启动一个 Web/API 进程并验证旧入口。

如果出现迁移或数据结构异常，应停止所有写入，保留异常数据库副本，然后恢复启用前的完整备份。不要在运行中覆盖 SQLite 文件，也不要只删除新身份表。

## 十四、生产部署注意事项

- SQLite 只运行一个 Web/API 进程，不要使用多个 Uvicorn worker。
- 分析内部仍可使用线程并发，但任务队列和 SSE 订阅状态当前属于单进程状态。
- 公网必须使用 HTTPS；Web 静态页面和 `/api` 必须同源。
- 不要在直连公网时信任客户端自行传入的 forwarded headers。
- PostgreSQL、水平扩容、MFA、OIDC、组织空间、API Key/服务账号登录和 Bot 独立身份不属于当前 P0 生产范围。

## 十五、管理员速查表

| 我要做什么 | 使用入口或命令 |
| --- | --- |
| 登录产品工作台 | [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) |
| 登录管理后台 | [http://127.0.0.1:8000/admin/login](http://127.0.0.1:8000/admin/login) |
| 使用邀请码注册 | [http://127.0.0.1:8000/accept-invite](http://127.0.0.1:8000/accept-invite) |
| 打开游客体验 | 访问 [http://127.0.0.1:8000/login](http://127.0.0.1:8000/login) 后点击“进入游客体验” |
| 初始化唯一 Owner | `.\.venv\Scripts\python.exe -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"` |
| 重置数据库用户密码 | `.\.venv\Scripts\python.exe -m src.auth reset_user_password --username <登录名>` |
| 启动本地服务 | `.\.venv\Scripts\python.exe main.py --serve-only --host 127.0.0.1 --port 8000` |
