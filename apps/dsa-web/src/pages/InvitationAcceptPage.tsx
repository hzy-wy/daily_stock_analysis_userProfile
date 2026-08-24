import type React from 'react';
import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { authApi } from '../api/auth';
import { getParsedApiError } from '../api/error';
import { Button, Input } from '../components/common';

const InvitationAcceptPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [token, setToken] = useState(searchParams.get('token') ?? '');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== passwordConfirm) {
      setError('两次输入的密码不一致');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await authApi.acceptInvitation(token.trim(), displayName.trim(), password, passwordConfirm);
      navigate('/login', { replace: true });
    } catch (err) {
      setError(getParsedApiError(err).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-[100dvh] items-center justify-center bg-base px-6 py-10">
      <form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-2xl">
        <ShieldCheck className="h-8 w-8 text-primary" />
        <h1 className="mt-5 text-2xl font-semibold text-foreground">接受工作区邀请</h1>
        <p className="mt-2 text-sm leading-6 text-secondary-text">设置显示名称和独立密码后，即可使用自己的私有投研空间。</p>
        <div className="mt-7 space-y-4">
          <Input label="邀请令牌" value={token} onChange={(event) => setToken(event.target.value)} required autoFocus={!token} />
          <Input label="显示名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required autoFocus={Boolean(token)} autoComplete="name" />
          <Input label="密码（至少 12 位）" type="password" allowTogglePassword iconType="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={12} autoComplete="new-password" />
          <Input label="确认密码" type="password" allowTogglePassword iconType="password" value={passwordConfirm} onChange={(event) => setPasswordConfirm(event.target.value)} required minLength={12} autoComplete="new-password" />
        </div>
        {error ? <p role="alert" className="mt-4 text-sm text-danger">{error}</p> : null}
        <Button type="submit" variant="primary" size="lg" className="mt-6 w-full" isLoading={busy}>创建账号</Button>
      </form>
    </main>
  );
};

export default InvitationAcceptPage;
