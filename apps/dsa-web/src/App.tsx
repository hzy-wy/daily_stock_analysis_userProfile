import type React from 'react';
import { lazy, useEffect, useLayoutEffect } from 'react';
import { BrowserRouter as Router, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { ApiErrorAlert, LoginRequiredDialog, Shell } from './components/common';
import {
  PageLoadingFallback,
  RouteOutletBoundary,
  StandaloneRouteBoundary,
} from './components/layout/RouteBoundary';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { UiLanguageProvider, useUiLanguage } from './contexts/UiLanguageContext';
import { useAgentChatStore } from './stores/agentChatStore';
import './App.css';

const HomePage = lazy(() => import('./pages/HomePage'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const AdminConsolePage = lazy(() => import('./pages/AdminConsolePage'));
const InvitationAcceptPage = lazy(() => import('./pages/InvitationAcceptPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'));
const DecisionSignalsPage = lazy(() => import('./pages/DecisionSignalsPage'));
const AlertsPage = lazy(() => import('./pages/AlertsPage'));
const TokenUsagePage = lazy(() => import('./pages/TokenUsagePage'));
const StockScreeningPage = lazy(() => import('./pages/StockScreeningPage'));

const AuthenticatedOnly: React.FC<{ children: React.ReactNode; reason: string }> = ({ children, reason }) => {
  const { authEnabled, guestMode, loggedIn, requestLogin } = useAuth();

  useEffect(() => {
    if (guestMode && !loggedIn) requestLogin(reason);
  }, [guestMode, loggedIn, reason, requestLogin]);

  if (authEnabled && !loggedIn) return <Navigate to="/" replace />;
  return <>{children}</>;
};

const AppContent: React.FC = () => {
  const location = useLocation();
  const {
    authEnabled,
    guestMode,
    loggedIn,
    isLoading,
    loadError,
    refreshStatus,
    user,
  } = useAuth();
  const { t } = useUiLanguage();

  useEffect(() => {
    useAgentChatStore.getState().setCurrentRoute(location.pathname);
  }, [location.pathname]);

  useLayoutEffect(() => {
    useAgentChatStore.getState().setGuestMode(guestMode && !loggedIn);
  }, [guestMode, loggedIn]);

  if (location.pathname === '/admin' || location.pathname.startsWith('/admin/')) {
    return (
      <StandaloneRouteBoundary>
        <AdminConsolePage />
      </StandaloneRouteBoundary>
    );
  }

  if (location.pathname === '/accept-invite') {
    return (
      <StandaloneRouteBoundary>
        <InvitationAcceptPage />
      </StandaloneRouteBoundary>
    );
  }

  if (isLoading) {
    return <PageLoadingFallback />;
  }

  if (loadError) {
    return (
      <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-4 bg-base px-4">
        <div className="w-full max-w-lg">
          <ApiErrorAlert error={loadError} />
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => void refreshStatus()}
        >
          {t('common.retry')}
        </button>
      </div>
    );
  }

  if (location.pathname === '/login') {
    if (loggedIn) return <Navigate to="/" replace />;
    return (
      <StandaloneRouteBoundary>
        <LoginPage />
      </StandaloneRouteBoundary>
    );
  }

  if (authEnabled && !loggedIn && !guestMode) {
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }

  const canConfigureSystem = !authEnabled || Boolean(
    user && (user.permissions.includes('*') || user.permissions.includes('system.configure')),
  );

  const requireAuthenticated = (node: React.ReactNode, reason: string) => (
    <AuthenticatedOnly reason={reason}>{node}</AuthenticatedOnly>
  );

  return (
    <>
      <Routes>
        <Route
          element={(
            <Shell>
              <RouteOutletBoundary />
            </Shell>
          )}
        >
          <Route path="/" element={<HomePage guestMode={guestMode && !loggedIn} />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/portfolio" element={<PortfolioPage guestMode={guestMode && !loggedIn} />} />
          <Route
            path="/decision-signals"
            element={requireAuthenticated(
              <DecisionSignalsPage />,
              'AI 问股可直接体验；AI 建议记录、回测反馈与状态管理需要登录后保存到个人空间。',
            )}
          />
          <Route path="/screening" element={<StockScreeningPage />} />
          <Route path="/backtest" element={requireAuthenticated(<BacktestPage />, '回测结果会关联到个人工作区，请先登录。')} />
          <Route path="/alerts" element={requireAuthenticated(<AlertsPage />, '预警规则需要持续保存并关联到你的账号，请先登录。')} />
          <Route path="/usage" element={requireAuthenticated(<TokenUsagePage />, '用量统计属于账号数据，请先登录。')} />
          <Route
            path="/settings"
            element={canConfigureSystem
              ? <SettingsPage />
              : requireAuthenticated(<Navigate to="/" replace />, '系统设置仅对有权限的登录用户开放。')}
          />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
      <LoginRequiredDialog />
    </>
  );
};

const App: React.FC = () => {
  return (
    <UiLanguageProvider>
      <Router>
        <AuthProvider>
          <AppContent />
        </AuthProvider>
      </Router>
    </UiLanguageProvider>
  );
};

export default App;
