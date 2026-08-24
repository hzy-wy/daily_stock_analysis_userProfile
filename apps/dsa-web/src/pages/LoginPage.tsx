import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { useGSAP } from '@gsap/react';
import { gsap } from 'gsap';
import { ArrowRight, Cpu, LineChart, Lock, ShieldCheck, Sparkles } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { ParsedApiError } from '../api/error';
import { isParsedApiError } from '../api/error';
import { Button, Input, ParticleBackground } from '../components/common';
import { UiLanguageToggle } from '../components/i18n/UiLanguageToggle';
import { SettingsAlert } from '../components/settings';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useAuth } from '../hooks';

gsap.registerPlugin(useGSAP);

type LoginMotionConditions = {
  finePointer: boolean;
  reduceMotion: boolean;
};

const LoginPage: React.FC = () => {
  const { authMode, login, passwordSet, setupState } = useAuth();
  const { language, t } = useUiLanguage();
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);
  const primaryGlowRef = useRef<HTMLDivElement>(null);
  const secondaryGlowRef = useRef<HTMLDivElement>(null);
  const brandMarkRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = t('login.pageTitle');
  }, [t]);

  const [searchParams] = useSearchParams();
  const rawRedirect = searchParams.get('redirect') ?? '';
  const redirect = rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : '/';

  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | ParsedApiError | null>(null);

  const isMultiUser = authMode === 'multi_user';
  const isFirstTime = !isMultiUser && (setupState === 'no_password' || !passwordSet);
  const copy = language === 'en'
    ? {
      kicker: 'Research operating system',
      headlineWords: ['Turn market noise', 'into clear decisions'],
      description: 'A focused workspace for multi-market research, portfolio context and AI-assisted analysis.',
      capabilities: [
        ['Coverage', 'A shares / HK / US'],
        ['Research', 'Technicals / News / AI'],
        ['Workflow', 'Live tasks / Review'],
      ],
      access: 'Workspace access',
      security: 'Local credential check / secure session transport',
    }
    : {
      kicker: '智能投研操作系统',
      headlineWords: ['让每一次判断', '都有数据依据'],
      description: '把多市场行情、持仓上下文与 AI 分析汇入一个专注、可信的工作台。',
      capabilities: [
        ['市场覆盖', 'A股 / 港股 / 美股'],
        ['研判链路', '技术面 / 新闻 / AI'],
        ['工作模式', '实时任务 / 历史复盘'],
      ],
      access: '工作台访问',
      security: '本地凭证校验 / 会话安全传输',
    };

  useGSAP((_, contextSafe) => {
    const root = rootRef.current;
    if (!root) return;

    const media = gsap.matchMedia();
    media.add(
      {
        finePointer: '(pointer: fine)',
        reduceMotion: '(prefers-reduced-motion: reduce)',
      },
      (context) => {
        const { finePointer, reduceMotion } = context.conditions as LoginMotionConditions;

        if (reduceMotion) {
          gsap.set('.login-reveal, .login-word, .login-metric', { autoAlpha: 1, clearProps: 'transform' });
        } else {
          const timeline = gsap.timeline({ defaults: { ease: 'power3.out' } });
          timeline
            .fromTo('.login-brand-mark', { autoAlpha: 0, scale: 0.84, rotation: -6 }, {
              autoAlpha: 1,
              scale: 1,
              rotation: 0,
              duration: 0.58,
            })
            .fromTo('.login-kicker', { autoAlpha: 0, y: 14 }, {
              autoAlpha: 1,
              y: 0,
              duration: 0.42,
            }, '<0.1')
            .fromTo('.login-word', { autoAlpha: 0, yPercent: 110, rotation: 2 }, {
              autoAlpha: 1,
              yPercent: 0,
              rotation: 0,
              duration: 0.68,
              stagger: 0.08,
              clearProps: 'opacity,visibility,transform',
            }, '<0.08')
            .fromTo('.login-description', { autoAlpha: 0, y: 16 }, {
              autoAlpha: 1,
              y: 0,
              duration: 0.48,
              clearProps: 'opacity,visibility,transform',
            }, '<0.18')
            .fromTo('.login-metric', { autoAlpha: 0, y: 18 }, {
              autoAlpha: 1,
              y: 0,
              duration: 0.42,
              stagger: 0.07,
              clearProps: 'opacity,visibility,transform',
            }, '<0.08')
            .fromTo('.login-form-shell', { autoAlpha: 0, x: 28, scale: 0.985 }, {
              autoAlpha: 1,
              x: 0,
              scale: 1,
              duration: 0.62,
              clearProps: 'opacity,visibility,transform',
            }, 0.18)
            .fromTo('.login-form-field', { autoAlpha: 0, y: 12 }, {
              autoAlpha: 1,
              y: 0,
              duration: 0.38,
              stagger: 0.055,
              clearProps: 'opacity,visibility,transform',
            }, '<0.18');
        }

        if (!finePointer || reduceMotion || !contextSafe) return;

        const primaryGlow = primaryGlowRef.current;
        const secondaryGlow = secondaryGlowRef.current;
        const brandMark = brandMarkRef.current;
        if (!primaryGlow || !secondaryGlow || !brandMark) return;

        const movePrimaryX = gsap.quickTo(primaryGlow, 'x', { duration: 0.52, ease: 'power3.out' });
        const movePrimaryY = gsap.quickTo(primaryGlow, 'y', { duration: 0.52, ease: 'power3.out' });
        const moveSecondaryX = gsap.quickTo(secondaryGlow, 'x', { duration: 0.62, ease: 'power3.out' });
        const moveSecondaryY = gsap.quickTo(secondaryGlow, 'y', { duration: 0.62, ease: 'power3.out' });
        const moveMarkX = gsap.quickTo(brandMark, 'x', { duration: 0.34, ease: 'power2.out' });
        const moveMarkY = gsap.quickTo(brandMark, 'y', { duration: 0.34, ease: 'power2.out' });

        const handlePointerMove = contextSafe((event: PointerEvent) => {
          const x = event.clientX / window.innerWidth - 0.5;
          const y = event.clientY / window.innerHeight - 0.5;
          movePrimaryX(x * 46);
          movePrimaryY(y * 38);
          moveSecondaryX(x * -32);
          moveSecondaryY(y * -28);
          moveMarkX(x * 7);
          moveMarkY(y * 7);
        });
        const handlePointerLeave = contextSafe(() => {
          movePrimaryX(0);
          movePrimaryY(0);
          moveSecondaryX(0);
          moveSecondaryY(0);
          moveMarkX(0);
          moveMarkY(0);
        });

        root.addEventListener('pointermove', handlePointerMove, { passive: true });
        root.addEventListener('pointerleave', handlePointerLeave);

        return () => {
          root.removeEventListener('pointermove', handlePointerMove);
          root.removeEventListener('pointerleave', handlePointerLeave);
        };
      },
      root,
    );

    return () => media.revert();
  }, { scope: rootRef });

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (isMultiUser && !identifier.trim()) {
      setError(language === 'en' ? 'Enter your username or email.' : '请输入用户名或邮箱。');
      return;
    }
    if (isFirstTime && password !== passwordConfirm) {
      setError(t('login.passwordMismatch'));
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await login(
        password,
        isFirstTime ? passwordConfirm : undefined,
        isMultiUser ? identifier.trim() : undefined,
      );
      if (result.success) {
        navigate(redirect, { replace: true });
      } else {
        setError(result.error ?? t('login.loginFailed'));
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      ref={rootRef}
      className="login-experience relative grid min-h-[100dvh] overflow-hidden bg-[var(--login-bg-main)] font-sans selection:bg-[var(--login-accent-soft)] lg:grid-cols-[minmax(0,1.15fr)_minmax(26rem,0.85fr)]"
    >
      <ParticleBackground />
      <div className="login-grid pointer-events-none absolute inset-0" aria-hidden="true" />
      <div ref={primaryGlowRef} className="login-ambient login-ambient--primary" aria-hidden="true" />
      <div ref={secondaryGlowRef} className="login-ambient login-ambient--secondary" aria-hidden="true" />

      <div className="absolute right-4 top-4 z-30">
        <UiLanguageToggle />
      </div>

      <section className="relative z-10 flex min-h-[42vh] items-end px-5 pb-8 pt-20 sm:px-8 lg:min-h-[100dvh] lg:items-center lg:px-12 lg:py-16 xl:px-20">
        <div className="w-full max-w-3xl">
          <div ref={brandMarkRef} className="login-brand-mark mb-8 inline-flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--login-accent-border)] bg-[var(--login-accent-soft)] text-[var(--login-accent-text)] shadow-[inset_0_1px_0_hsl(0_0%_100%_/_0.16)]">
              <LineChart className="h-6 w-6" aria-hidden="true" />
            </span>
            <span>
              <strong className="block text-lg font-semibold tracking-[-0.02em] text-[var(--login-text-primary)]">DSA</strong>
              <small className="block text-xs text-[var(--login-text-muted)]">Daily Stock Analysis</small>
            </span>
          </div>

          <p className="login-kicker mb-4 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--login-accent-text)]">
            {copy.kicker}
          </p>
          <h1 className="max-w-[13ch] text-[clamp(2.7rem,6.2vw,6.8rem)] font-semibold leading-[0.94] tracking-[-0.055em] text-[var(--login-text-primary)]">
            {copy.headlineWords.map((line, index) => (
              <span key={line} className="login-word-mask block overflow-hidden pb-[0.08em]">
                <span className={index === 1 ? 'login-word block text-[var(--login-accent-text)]' : 'login-word block'}>
                  {line}
                </span>
              </span>
            ))}
          </h1>
          <p className="login-description mt-6 max-w-xl text-sm leading-7 text-[var(--login-text-secondary)] sm:text-[1rem]">
            {copy.description}
          </p>

          <div className="mt-8 grid max-w-2xl grid-cols-1 gap-2 sm:grid-cols-3">
            {copy.capabilities.map(([label, value]) => (
              <div key={label} className="login-metric rounded-2xl border border-[var(--login-border-card)] bg-[var(--login-bg-card)]/52 p-4 backdrop-blur-md">
                <span className="block text-[11px] font-medium text-[var(--login-text-muted)]">{label}</span>
                <strong className="mt-1.5 block text-sm font-semibold leading-5 text-[var(--login-text-primary)]">{value}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <main className="relative z-20 flex items-center justify-center px-5 pb-10 sm:px-8 lg:min-h-[100dvh] lg:px-10 lg:py-16">
        <div className="login-form-shell w-full max-w-md rounded-2xl border border-[var(--login-border-card)] bg-[var(--login-bg-card)]/88 p-6 shadow-[0_28px_90px_hsl(220_74%_4%_/_0.28)] backdrop-blur-2xl sm:p-8">
          <div className="login-form-field mb-8 flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium text-[var(--login-accent-text)]">{copy.access}</p>
              <h2 className="mt-2 flex items-center gap-2 text-2xl font-semibold tracking-[-0.025em] text-[var(--login-text-primary)]">
                {isFirstTime ? (
                  <ShieldCheck className="h-5 w-5 text-[var(--login-accent-text)]" aria-hidden="true" />
                ) : (
                  <Lock className="h-5 w-5 text-[var(--login-accent-text)]" aria-hidden="true" />
                )}
                <span>
                  {isFirstTime
                    ? t('login.setupTitle')
                    : isMultiUser
                      ? t('login.workspaceLogin')
                      : t('login.adminLogin')}
                </span>
              </h2>
              <p className="mt-2 text-sm leading-6 text-[var(--login-text-secondary)]">
                {isFirstTime ? t('login.setupDescription') : t('login.loginDescription')}
              </p>
            </div>
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--login-border-card)] bg-[var(--login-accent-soft)] text-[var(--login-accent-text)]">
              <Cpu className="h-5 w-5" aria-hidden="true" />
            </span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-4">
              {isMultiUser ? (
                <div className="login-form-field">
                  <Input
                    id="identifier"
                    type="text"
                    appearance="login"
                    label={language === 'en' ? 'Username or email' : '用户名或邮箱'}
                    placeholder={language === 'en' ? 'Enter your account identifier' : '请输入账号标识'}
                    value={identifier}
                    onChange={(event) => setIdentifier(event.target.value)}
                    disabled={isSubmitting}
                    autoFocus
                    autoComplete="username"
                  />
                </div>
              ) : null}
              <div className="login-form-field">
                <Input
                  id="password"
                  type="password"
                  appearance="login"
                  allowTogglePassword
                  iconType="password"
                  label={isFirstTime ? t('login.adminPassword') : t('login.loginPassword')}
                  placeholder={isFirstTime ? t('login.setupPasswordPlaceholder') : t('login.loginPasswordPlaceholder')}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={isSubmitting}
                  autoFocus={!isMultiUser}
                  autoComplete={isFirstTime ? 'new-password' : 'current-password'}
                />
              </div>

              {isFirstTime ? (
                <div className="login-form-field">
                  <Input
                    id="passwordConfirm"
                    type="password"
                    appearance="login"
                    allowTogglePassword
                    iconType="password"
                    label={t('login.confirmPassword')}
                    placeholder={t('login.confirmPasswordPlaceholder')}
                    value={passwordConfirm}
                    onChange={(event) => setPasswordConfirm(event.target.value)}
                    disabled={isSubmitting}
                    autoComplete="new-password"
                  />
                </div>
              ) : null}
            </div>

            {error ? (
              <div className="login-form-field">
                <SettingsAlert
                  title={isFirstTime ? t('login.setupFailed') : t('login.validationFailed')}
                  message={isParsedApiError(error) ? error.message : error}
                  variant="error"
                  className="!border-[var(--login-error-border)] !bg-[var(--login-error-bg)] !text-[var(--login-error-text)]"
                />
              </div>
            ) : null}

            <div className="login-form-field">
              <Button
                type="submit"
                variant="primary"
                size="lg"
                isLoading={isSubmitting}
                loadingText={isFirstTime ? t('login.setupSubmitting') : t('login.loginSubmitting')}
                className="group h-12 w-full justify-between rounded-xl border-[var(--login-accent-border)] bg-[var(--login-brand-button-start)] px-4 text-[var(--login-button-text)] shadow-[0_16px_40px_hsl(214_100%_8%_/_0.2)] hover:bg-[var(--login-brand-button-start-hover)]"
              >
                <span>{isFirstTime ? t('login.setupSubmit') : t('login.loginSubmit')}</span>
                <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover:translate-x-1" aria-hidden="true" />
              </Button>
            </div>
          </form>

          <div className="login-form-field mt-6 flex items-center gap-2 border-t border-[var(--login-border-card)] pt-5 text-xs text-[var(--login-text-muted)]">
            <Sparkles className="h-3.5 w-3.5 text-[var(--login-accent-text)]" aria-hidden="true" />
            <span>{copy.security}</span>
          </div>
        </div>
      </main>
    </div>
  );
};

export default LoginPage;
