import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { CircleHelp, LogOut, RefreshCw, ShieldCheck, UserPlus, Users } from 'lucide-react';
import { adminApi, type AdminStatus, type AdminUser, type AuditLogItem } from '../api/admin';
import { getParsedApiError } from '../api/error';
import { Button, Input } from '../components/common';
import { AdminOnboarding, replayOnboarding } from '../components/onboarding';

const roleLabels: Record<string, string> = {
  member: '普通用户',
  auditor: '审计员',
  platform_admin: '平台管理员',
  platform_owner: '平台所有者',
};

const AdminConsolePage: React.FC = () => {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [inviteIdentifier, setInviteIdentifier] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const nextStatus = await adminApi.getStatus();
      setStatus(nextStatus);
      const permissions = nextStatus.user?.permissions ?? [];
      const has = (permission: string) => permissions.includes('*') || permissions.includes(permission);
      setUsers(nextStatus.loggedIn && has('users.manage') ? await adminApi.listUsers() : []);
      setAuditLogs(nextStatus.loggedIn && has('audit.read') ? await adminApi.listAuditLogs() : []);
    } catch (err) {
      setError(getParsedApiError(err).message);
    }
  }, []);

  useEffect(() => {
    document.title = 'DSA · 管理后台';
    void refresh();
  }, [refresh]);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminApi.login(identifier.trim(), password);
      setPassword('');
      await refresh();
    } catch (err) {
      setError(getParsedApiError(err).message);
    } finally {
      setBusy(false);
    }
  };

  if (!status) {
    return <div className="flex min-h-[100dvh] items-center justify-center bg-base text-secondary-text">正在加载管理后台…</div>;
  }

  if (status.authMode !== 'multi_user') {
    return (
      <main className="flex min-h-[100dvh] items-center justify-center bg-base px-6">
        <section className="w-full max-w-lg rounded-2xl border border-border bg-surface p-8">
          <ShieldCheck className="h-8 w-8 text-primary" />
          <h1 className="mt-5 text-2xl font-semibold text-foreground">多用户管理后台未启用</h1>
          <p className="mt-3 text-sm leading-6 text-secondary-text">将环境变量 AUTH_MODE 设置为 multi_user，并在受信任终端创建首个平台所有者。</p>
        </section>
      </main>
    );
  }

  if (!status.loggedIn) {
    return (
      <main className="flex min-h-[100dvh] items-center justify-center bg-base px-6">
        <form onSubmit={handleLogin} className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-2xl">
          <ShieldCheck className="h-8 w-8 text-primary" />
          <h1 className="mt-5 text-2xl font-semibold text-foreground">管理员登录</h1>
          <p className="mt-2 text-sm text-secondary-text">该入口使用独立的管理员会话，不会覆盖产品工作台登录。</p>
          <div className="mt-7 space-y-4">
            <Input label="用户名或邮箱" value={identifier} onChange={(event) => setIdentifier(event.target.value)} autoComplete="username" required autoFocus />
            <Input label="密码" type="password" allowTogglePassword iconType="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </div>
          {error ? <p role="alert" className="mt-4 text-sm text-danger">{error}</p> : null}
          <Button type="submit" variant="primary" size="lg" className="mt-6 w-full" isLoading={busy}>进入管理后台</Button>
        </form>
      </main>
    );
  }

  const handleInvite = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const invitation = await adminApi.invite(inviteIdentifier.trim(), inviteRole);
      setInviteToken(invitation.token);
      setInviteIdentifier('');
    } catch (err) {
      setError(getParsedApiError(err).message);
    } finally {
      setBusy(false);
    }
  };

  const mutateUser = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await operation();
      await refresh();
    } catch (err) {
      setError(getParsedApiError(err).message);
    } finally {
      setBusy(false);
    }
  };
  const canManageUsers = Boolean(
    status.user?.permissions.includes('*') || status.user?.permissions.includes('users.manage'),
  );

  return (
    <>
    <main className="min-h-[100dvh] bg-base px-5 py-8 text-foreground sm:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">DSA identity control plane</p>
            <h1 className="mt-2 text-3xl font-semibold">用户与权限</h1>
            <p className="mt-2 text-sm text-secondary-text">当前管理员：{status.user?.displayName}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => replayOnboarding('admin')}><CircleHelp className="h-4 w-4" />新手导览</Button>
            <Button variant="secondary" data-onboarding="admin-refresh" onClick={() => void refresh()}><RefreshCw className="h-4 w-4" />刷新</Button>
            <Button variant="secondary" onClick={() => void (async () => { await adminApi.logout(); await refresh(); })()}><LogOut className="h-4 w-4" />退出</Button>
          </div>
        </header>

        {error ? <div role="alert" className="mt-5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</div> : null}

        {canManageUsers ? <section className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="overflow-hidden rounded-2xl border border-border bg-surface" data-onboarding="admin-users">
            <div className="flex items-center gap-3 border-b border-border px-5 py-4"><Users className="h-5 w-5 text-primary" /><h2 className="font-semibold">平台用户</h2></div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[44rem] text-left text-sm">
                <thead className="bg-muted/30 text-xs text-secondary-text"><tr><th className="px-5 py-3">用户</th><th className="px-5 py-3">角色</th><th className="px-5 py-3">状态</th><th className="px-5 py-3">操作</th></tr></thead>
                <tbody className="divide-y divide-border">
                  {users.map((user) => {
                    const protectedOwner = user.roles.includes('platform_owner');
                    return (
                      <tr key={user.id}>
                        <td className="px-5 py-4"><strong className="block">{user.displayName}</strong><span className="text-xs text-secondary-text">{user.identifier}</span></td>
                        <td className="px-5 py-4">
                          {protectedOwner ? roleLabels.platform_owner : (
                            <select className="input-surface rounded-lg border px-2 py-1.5" value={user.roles[0] ?? 'member'} disabled={busy} onChange={(event) => void mutateUser(() => adminApi.updateRole(user.id, event.target.value))}>
                              <option value="member">普通用户</option><option value="auditor">审计员</option><option value="platform_admin">平台管理员</option>
                            </select>
                          )}
                        </td>
                        <td className="px-5 py-4">{user.status}</td>
                        <td className="px-5 py-4">{protectedOwner ? '受保护' : <Button variant="secondary" size="sm" disabled={busy} onClick={() => void mutateUser(() => adminApi.updateStatus(user.id, user.status === 'active' ? 'suspended' : 'active'))}>{user.status === 'active' ? '停用' : '启用'}</Button>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <form onSubmit={handleInvite} className="h-fit rounded-2xl border border-border bg-surface p-5">
            <div className="flex items-center gap-3"><UserPlus className="h-5 w-5 text-primary" /><h2 className="font-semibold">邀请用户</h2></div>
            <div className="mt-5 space-y-4">
              <Input label="用户名或邮箱" value={inviteIdentifier} onChange={(event) => setInviteIdentifier(event.target.value)} required />
              <label className="block text-sm font-medium">角色<select data-onboarding="admin-role-select" className="input-surface mt-2 h-11 w-full rounded-xl border px-3" value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}><option value="member">普通用户</option><option value="auditor">审计员</option><option value="platform_admin">平台管理员</option></select></label>
            </div>
            <Button type="submit" variant="primary" className="mt-5 w-full" isLoading={busy}>生成邀请</Button>
            {inviteToken ? <div className="mt-5 rounded-xl border border-warning/30 bg-warning/10 p-3"><p className="text-xs font-semibold text-warning">邀请令牌仅显示一次</p><code className="mt-2 block break-all text-xs">{inviteToken}</code></div> : null}
          </form>
        </section> : null}

        <section className="mt-8 overflow-hidden rounded-2xl border border-border bg-surface" data-onboarding="admin-audit-logs">
          <div className="flex items-center gap-3 border-b border-border px-5 py-4"><ShieldCheck className="h-5 w-5 text-primary" /><h2 className="font-semibold">审计日志</h2></div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] text-left text-sm">
              <thead className="bg-muted/30 text-xs text-secondary-text"><tr><th className="px-5 py-3">时间</th><th className="px-5 py-3">操作</th><th className="px-5 py-3">资源</th><th className="px-5 py-3">结果</th></tr></thead>
              <tbody className="divide-y divide-border">
                {auditLogs.map((item) => <tr key={item.id}><td className="px-5 py-3 text-secondary-text">{new Date(item.createdAt).toLocaleString()}</td><td className="px-5 py-3">{item.action}</td><td className="px-5 py-3 text-secondary-text">{item.resourceId ?? item.resourceType ?? '—'}</td><td className="px-5 py-3">{item.outcome}</td></tr>)}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
    {status.user ? <AdminOnboarding user={status.user} /> : null}
    </>
  );
};

export default AdminConsolePage;
