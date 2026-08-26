import type React from 'react';
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '../api/error';
import { authApi } from '../api/auth';
import { useStockPoolStore } from '../stores';
import {
  GUEST_SESSION_STORAGE_KEY,
  LOGIN_REQUIRED_EVENT,
  isGuestSessionActive,
  setGuestSessionActive,
} from '../utils/guestAccess';

type AuthContextValue = {
  authEnabled: boolean;
  authMode: 'disabled' | 'legacy' | 'multi_user';
  loggedIn: boolean;
  guestAccessEnabled: boolean;
  guestMode: boolean;
  user: {
    id: string;
    displayName: string;
    roles: string[];
    permissions: string[];
  } | null;
  passwordSet: boolean;
  passwordChangeable: boolean;
  setupState: 'enabled' | 'password_retained' | 'no_password' | 'bootstrap_required';
  isLoading: boolean;
  loadError: ParsedApiError | null;
  login: (
    password: string,
    passwordConfirm?: string,
    identifier?: string,
  ) => Promise<{ success: boolean; error?: ParsedApiError }>;
  changePassword: (
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string
  ) => Promise<{ success: boolean; error?: ParsedApiError }>;
  logout: () => Promise<void>;
  enterGuestMode: () => void;
  exitGuestMode: () => void;
  loginPrompt: { reason?: string } | null;
  requestLogin: (reason?: string) => void;
  dismissLoginPrompt: () => void;
  refreshStatus: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function extractLoginError(err: unknown): ParsedApiError {
  const parsed = getParsedApiError(err);
  if (parsed.status === 429) {
    return createParsedApiError({
      title: '登录尝试过于频繁',
      message: '尝试次数过多，请稍后再试。',
      rawMessage: parsed.rawMessage,
      status: parsed.status,
      category: parsed.category,
    });
  }
  return parsed;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authMode, setAuthMode] = useState<'disabled' | 'legacy' | 'multi_user'>('disabled');
  const [loggedIn, setLoggedIn] = useState(false);
  const [guestAccessEnabled, setGuestAccessEnabled] = useState(false);
  const [guestMode, setGuestMode] = useState(isGuestSessionActive);
  const [loginPrompt, setLoginPrompt] = useState<{ reason?: string } | null>(null);
  const [user, setUser] = useState<AuthContextValue['user']>(null);
  const [passwordSet, setPasswordSet] = useState(false);
  const [passwordChangeable, setPasswordChangeable] = useState(false);
  const [setupState, setSetupState] = useState<AuthContextValue['setupState']>('no_password');
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<ParsedApiError | null>(null);

  const fetchStatus = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const status = await authApi.getStatus();
      setAuthEnabled(status.authEnabled);
      setAuthMode(status.authMode ?? (status.authEnabled ? 'legacy' : 'disabled'));
      setLoggedIn(status.loggedIn);
      const nextGuestAccessEnabled = status.guestAccessEnabled ?? false;
      setGuestAccessEnabled(nextGuestAccessEnabled);
      setUser(status.user ?? null);
      setPasswordSet(status.passwordSet ?? false);
      setPasswordChangeable(status.passwordChangeable ?? false);
      setSetupState(status.setupState ?? (status.authEnabled ? 'enabled' : 'no_password'));
      if (status.loggedIn || !nextGuestAccessEnabled) {
        setGuestSessionActive(false);
        setGuestMode(false);
      } else {
        setGuestMode(isGuestSessionActive());
      }
      if (status.authEnabled && !status.loggedIn && !isGuestSessionActive()) {
        useStockPoolStore.getState().resetDashboardState();
      }
    } catch (err) {
      setLoadError(getParsedApiError(err));
      setAuthEnabled(false);
      setAuthMode('disabled');
      setLoggedIn(false);
      setGuestAccessEnabled(false);
      setGuestSessionActive(false);
      setGuestMode(false);
      setUser(null);
      setPasswordSet(false);
      setPasswordChangeable(false);
      setSetupState('no_password');
      useStockPoolStore.getState().resetDashboardState();
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === GUEST_SESSION_STORAGE_KEY) {
        setGuestMode(guestAccessEnabled && event.newValue === 'active');
      }
    };
    const handleLoginRequired = (event: Event) => {
      const customEvent = event as CustomEvent<{ reason?: string }>;
      setLoginPrompt({ reason: customEvent.detail?.reason });
    };
    window.addEventListener('storage', handleStorage);
    window.addEventListener(LOGIN_REQUIRED_EVENT, handleLoginRequired);
    return () => {
      window.removeEventListener('storage', handleStorage);
      window.removeEventListener(LOGIN_REQUIRED_EVENT, handleLoginRequired);
    };
  }, [guestAccessEnabled]);

  const login = useCallback(
    async (
      password: string,
      passwordConfirm?: string,
      identifier?: string,
    ): Promise<{ success: boolean; error?: ParsedApiError }> => {
      try {
        await authApi.login(password, passwordConfirm, identifier);
        setGuestSessionActive(false);
        setGuestMode(false);
        setLoginPrompt(null);
        await fetchStatus();
        return { success: true };
      } catch (err: unknown) {
        return { success: false, error: extractLoginError(err) };
      }
    },
    [fetchStatus]
  );

  const changePassword = useCallback(
    async (
      currentPassword: string,
      newPassword: string,
      newPasswordConfirm: string
    ): Promise<{ success: boolean; error?: ParsedApiError }> => {
      try {
        await authApi.changePassword(currentPassword, newPassword, newPasswordConfirm);
        return { success: true };
      } catch (err: unknown) {
        return { success: false, error: getParsedApiError(err) };
      }
    },
    []
  );

  const logout = useCallback(async () => {
    let logoutError: unknown = null;
    try {
      await authApi.logout();
    } catch (err) {
      logoutError = err;
    } finally {
      await fetchStatus();
    }

    if (logoutError && getParsedApiError(logoutError).status !== 401) {
      throw logoutError;
    }
  }, [fetchStatus]);

  const enterGuestMode = useCallback(() => {
    if (!guestAccessEnabled) return;
    setGuestSessionActive(true);
    setGuestMode(true);
    setLoginPrompt(null);
    useStockPoolStore.getState().resetDashboardState();
  }, [guestAccessEnabled]);

  const exitGuestMode = useCallback(() => {
    setGuestSessionActive(false);
    setGuestMode(false);
    setLoginPrompt(null);
    useStockPoolStore.getState().resetDashboardState();
  }, []);

  const requestLogin = useCallback((reason?: string) => {
    setLoginPrompt({ reason: reason?.trim() || undefined });
  }, []);

  const dismissLoginPrompt = useCallback(() => setLoginPrompt(null), []);

  return (
    <AuthContext.Provider
      value={{
        authEnabled,
        authMode,
        loggedIn,
        guestAccessEnabled,
        guestMode,
        user,
        passwordSet,
        passwordChangeable,
        setupState,
        isLoading,
        loadError,
        login,
        changePassword,
        logout,
        enterGuestMode,
        exitGuestMode,
        loginPrompt,
        requestLogin,
        dismissLoginPrompt,
        refreshStatus: fetchStatus,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- useAuth is a hook, co-located for context access
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
