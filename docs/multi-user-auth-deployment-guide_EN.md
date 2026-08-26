# Multi-user Authentication: Enablement, Validation, and Rollback

This is the operational companion to the [multi-user identity and RBAC PRD](multi-user-auth-rbac-prd.md). It covers the implemented P0 private multi-user deployment on the project's default SQLite database.

## 1. Implemented P0 scope

The current implementation includes local identities, Argon2id credentials, separate workspace/admin server-side sessions, Owner/Admin/Auditor/Member RBAC, trusted-terminal owner bootstrap and password reset, one-time invitations, user administration, audit logs, and owner isolation for analysis history, backtests, tasks, Agent conversations, portfolios, alerts, decision signals, usage, and Web watchlists.

Market quotes, public fundamentals, FX rates, and structured public market intelligence remain shared. Private reports and portfolios are not shared, and P0 does not give administrators a bypass for reading another user's private report body. Optional guest access uses the same workspace: public live-market reads and transient AI chat are available, while personal-data operations require sign-in.

MFA, OIDC/SSO, organizations, cross-user sharing, interactive API-key/service-account login, independent Bot identity, and the Desktop loopback handshake remain P1/P2 work. Desktop can currently use the same workspace login when it loads the Web service.

| Role | Workspace `/login` | Admin `/admin/login` | Scope |
| --- | --- | --- | --- |
| `platform_owner` | Yes | Yes | All permissions; protected from status/role replacement |
| `platform_admin` | Yes | Yes | User, system, audit, and workspace operations |
| `auditor` | No | Yes | Read-only audit access |
| `member` | Yes | No | Owned workspace resources |

Workspace and admin cookies are deliberately separate (`dsa_app_sid` and `dsa_admin_sid`). Logging out from one audience does not revoke the other.

Guest access has no separate route and is not an account, role, or authentication audience. A visitor selects “Enter guest experience” on `/login` and uses the normal workspace. Public live-market reads and transient AI chat are available; portfolios, saved watchlists, histories, alerts, and other personal-data capabilities require sign-in.

## 2. Preconditions and backup

- Python 3.11 is recommended. Install the current `requirements.txt`, including `argon2-cffi`.
- Use one Web/API server process. Analysis may still use thread concurrency through `MAX_WORKERS`, but the task queue and SSE subscriptions are process-local.
- Use same-origin Web and API URLs behind HTTPS for any public deployment.
- Stop the Web/API server, scheduler, and analyzer before backing up or migrating SQLite.

PowerShell backup example, run from the repository root:

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

If `DATABASE_PATH` points elsewhere, back up that actual database and the credential/session files in its directory.

## 3. Configuration

Set these explicitly in `.env`:

```dotenv
AUTH_MODE=multi_user
GUEST_ACCESS_ENABLED=false
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

An explicit `AUTH_MODE` overrides the legacy `ADMIN_AUTH_ENABLED` switch. Only enable `TRUST_X_FORWARDED_FOR` when every request passes through a controlled proxy that strips and rewrites forwarded client, protocol, and host headers.

Set `GUEST_ACCESS_ENABLED=true` to show the guest entry on `/login` and enable the server-side anonymous allowlist. `GUEST_AI_REQUESTS_PER_HOUR` limits transient AI requests per source IP and `GUEST_AI_MAX_HISTORY_MESSAGES` bounds browser-supplied temporary context. Restart the Web/API process after changing them.

## 4. Enable a fresh or previously disabled deployment

1. Install dependencies and build the Web client when running from source:

   ```powershell
   python -m pip install -r requirements.txt
   Set-Location apps/dsa-web
   npm ci
   npm run lint
   npm run build
   Set-Location ../..
   ```

2. Set `AUTH_MODE=multi_user` in `.env`.
3. Create the first owner from a trusted terminal. The password must be at least 12 characters and is not echoed:

   ```powershell
   python -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"
   ```

4. Start one server process:

   ```powershell
   python main.py --serve-only --host 127.0.0.1 --port 8000
   ```

Bind to `0.0.0.0` only after the firewall and HTTPS reverse proxy are configured.

## 5. Upgrade a legacy shared-password deployment

1. Keep the existing database and `.admin_password_hash` in the database directory.
2. Set `AUTH_MODE=multi_user` and the desired `MULTI_USER_LEGACY_OWNER_USERNAME`.
3. Run:

   ```powershell
   python -m src.auth bootstrap_owner --username owner
   ```

4. Initialization imports the legacy credential as the platform owner before prompting for a new password. The command should report that an owner is already available.
5. Sign in with `MULTI_USER_LEGACY_OWNER_USERNAME` and the old shared password. The first successful login upgrades the PBKDF2 verifier to Argon2id.
6. Verify that all legacy private data is visible only to this owner.

Running `bootstrap_owner` against an existing multi-user database is an idempotent check; it never replaces the owner or asks for a new password.

## 6. Docker Compose

After updating `.env` and backing up the host-mounted data:

```bash
docker compose -f docker/docker-compose.yml build server
docker compose -f docker/docker-compose.yml run --rm --no-deps -u dsa server \
  python -m src.auth bootstrap_owner --username owner --display-name "Deployment Owner"
docker compose -f docker/docker-compose.yml up -d server
docker compose -f docker/docker-compose.yml logs --tail=200 server
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:8000/api/v1/auth/status
```

The one-off bootstrap command uses the host-mounted `data/` directory. Do not scale the current `server` service to multiple replicas while its task queue remains process-local.

## 7. Automatic schema and ownership migration

The first CLI/API database initialization:

1. Creates users, identities, credentials, roles, permissions, assignments, sessions, invitations, audit/security events, and reserved API/service-account tables.
2. Adds nullable `owner_user_id` columns and indexes to private roots.
3. Rebuilds legacy SQLite global uniqueness for conversation summaries and backtest summaries into owner-scoped uniqueness.
4. Imports or creates the owner and assigns legacy private rows to that owner.
5. Keeps child ownership inherited through the report, conversation, portfolio account, alert rule, or decision signal.
6. Copies the legacy `STOCK_LIST` into the owner's Web watchlist once, recorded in `database_schema_migrations`.

Read-only identity-table check:

```powershell
python -c "from src.config import setup_env; setup_env(); import sqlite3, os; p=os.getenv('DATABASE_PATH','./data/stock_analysis.db'); c=sqlite3.connect(p); names={r[0] for r in c.execute('select name from sqlite_master where type=?', ('table',))}; required={'users','auth_identities','password_credentials','auth_sessions','roles','permissions','user_role_assignments','invitations','audit_logs','security_events'}; print('database=', p, 'missing=', sorted(required-names)); c.close()"
```

Proceed only when it prints `missing=[]`. Do not manually rewrite owner IDs or delete migration records.

## 8. First use and account operations

- Workspace login: `https://your-host/login`
- Administrator login: `https://your-host/admin/login`
- Invitation acceptance: `https://your-host/accept-invite`
- Guest entry: `https://your-host/login` (select “Enter guest experience”; there is no separate demo page)

An Owner or Platform Admin generates a one-time invitation in the admin console. Send the token over a trusted channel. The recipient may paste it into the acceptance page or use `/accept-invite?token=<token>`, then sets a display name and a password of at least 12 characters. Invitations expire after 72 hours by default and cannot be reused.

Do not place invitation tokens in issues, logs, screenshots, or public chat. A status or role change revokes the target user's sessions. The platform owner cannot be suspended or have the owner role replaced through the normal admin API.

Trusted-terminal password recovery:

```powershell
python -m src.auth reset_user_password --username <login>
```

This revokes all existing workspace and admin sessions for that user and records an audit event.

## 9. Reverse-proxy requirements

Use this topology:

```text
Browser --HTTPS--> controlled reverse proxy --private HTTP--> one DSA Web/API process
```

- Serve Web static content and `/api` on the exact same external origin.
- When HTTPS terminates at the proxy, rewrite `X-Forwarded-Proto=https`, `X-Forwarded-Host`, and `X-Forwarded-For`, then enable forwarded-header trust.
- Never expose the backend directly to untrusted clients while trusting client-supplied forwarded headers.
- Browser mutations enforce an exact Origin match. Fix proxy scheme/host forwarding if `invalid_origin` occurs; do not disable the check.
- Session cookies are `HttpOnly` and `SameSite=Lax`, and become `Secure` when the external request is recognized as HTTPS.

## 10. Mandatory validation

Use two browser profiles for Owner and Member.

- [ ] Unauthenticated private APIs return 401.
- [ ] If guest access is enabled, an unauthenticated visitor can enter the normal workspace from `/login`, read public live-market data, and use transient AI chat.
- [ ] Guest AI history disappears after refresh; no guest rows are added to `conversation_messages`, `agent_provider_turns`, or `llm_usage`; portfolio creation, watchlist persistence, private history, and other personal operations prompt for sign-in, and private APIs still return 401.
- [ ] Owner can hold workspace and admin sessions at the same time.
- [ ] Member can use the workspace but receives 403 on admin login.
- [ ] Auditor can read audit logs but cannot manage users or use the workspace.
- [ ] Logging out of admin leaves the workspace session active.
- [ ] Status/role changes invalidate the target user's sessions.
- [ ] Five recent failures for either a login identifier or a client IP trigger a 429 window.
- [ ] Owner and Member have separate watchlists, analysis/history/tasks/SSE, Agent sessions, portfolios and all-account aggregates, alerts, signals/outcomes, backtests/summaries, and usage.
- [ ] Changing a resource ID cannot read or write another user's child resource.
- [ ] Shared quotes, FX, and public market intelligence remain available to both.
- [ ] `/api/health` stays healthy and logs contain no migration failures, persistent locks, `bootstrap_required`, or repeated `invalid_origin` errors.

## 11. Troubleshooting

- `503 bootstrap_required`: confirm the effective `DATABASE_PATH`, stop the service, and run the owner bootstrap command.
- Owner already exists: expected idempotency. Use `reset_user_password` for recovery; do not delete identity tables.
- `legacy_identifier_conflict`: the configured legacy-owner login belongs to a non-owner account. Choose an unused `MULTI_USER_LEGACY_OWNER_USERNAME` and rerun bootstrap; the system deliberately refuses automatic promotion.
- Workspace is logged in but admin is not: expected; sign in separately at `/admin/login`.
- `403 invalid_origin`: correct external host/protocol forwarding and forwarded-header trust.
- `429`: the same identifier or client IP reached five failures within five minutes. Fix credentials/proxy aggregation and wait for the window.
- Legacy reports are absent: sign in as the imported owner and confirm the process uses the expected database.
- Persistent SQLite locks: stop duplicate server/analyzer writers, inspect long-running backups, and keep the DB/WAL on reliable local storage.

## 12. Rollback

For a soft authentication rollback, stop all processes and change `AUTH_MODE` to `legacy`. On a fresh multi-user deployment that never had a legacy shared password, run `python -m src.auth reset_password` from a trusted terminal before restarting the Web service so remote users cannot reach first-password setup. Use `disabled` only on a trusted non-public network. Restart one server and keep the new tables and ownership columns so multi-user mode can be re-enabled later.

For schema/data inconsistency, stop every writer, retain a copy of the failed database for diagnosis, restore the pre-migration database plus `.env`, `.admin_password_hash`, and `.session_secret`, restore the previous auth mode, and verify record counts before reopening traffic. Never overwrite a live SQLite file and never delete only the new identity tables.

## 13. Production boundary

The certified P0 path is SQLite, one Web/API process, and same-origin HTTPS through a controlled proxy. Although parts of the ORM model reserve PostgreSQL-compatible index predicates, the existing incremental migration, SQLite table rebuilds, portfolio locking, and integration suite do not yet constitute PostgreSQL production certification. Database replacement or horizontal scaling requires a dedicated migration, shared task queue, distributed throttling/SSE design, load tests, and failure drills.
