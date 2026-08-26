import type React from 'react';
import { createPortal } from 'react-dom';
import { LogIn, TicketCheck, X } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

export const LoginRequiredDialog: React.FC = () => {
  const { dismissLoginPrompt, loginPrompt } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  if (!loginPrompt || typeof document === 'undefined') return null;

  const redirect = location.pathname + location.search;
  const goToLogin = () => {
    dismissLoginPrompt();
    navigate(`/login?redirect=${encodeURIComponent(redirect)}`);
  };
  const goToInvitation = () => {
    dismissLoginPrompt();
    navigate('/accept-invite');
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-black/65 px-4 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) dismissLoginPrompt();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-required-title"
        className="w-full max-w-md rounded-2xl border border-border/70 bg-elevated p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">游客体验</p>
            <h2 id="login-required-title" className="mt-2 text-xl font-semibold text-foreground">
              登录后即可继续
            </h2>
          </div>
          <button
            type="button"
            onClick={dismissLoginPrompt}
            className="rounded-lg p-2 text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mt-4 text-sm leading-6 text-secondary-text">
          {loginPrompt.reason || '该功能需要创建、读取或修改你的个人数据，因此需要先登录账号。'}
        </p>
        <p className="mt-2 text-xs leading-5 text-muted-text">
          游客仍可继续查看真实行情，并使用不保存历史记录的 AI 问股。
        </p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <button type="button" className="btn-primary inline-flex items-center justify-center gap-2" onClick={goToLogin}>
            <LogIn className="h-4 w-4" />
            去登录
          </button>
          <button type="button" className="btn-secondary inline-flex items-center justify-center gap-2" onClick={goToInvitation}>
            <TicketCheck className="h-4 w-4" />
            使用邀请码注册
          </button>
        </div>
        <button
          type="button"
          className="mt-3 w-full rounded-lg px-4 py-2 text-sm text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
          onClick={dismissLoginPrompt}
        >
          继续游客体验
        </button>
      </section>
    </div>,
    document.body,
  );
};
