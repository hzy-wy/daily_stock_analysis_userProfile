import apiClient from './index';

export type AuthStatusResponse = {
  authEnabled: boolean;
  authMode?: 'disabled' | 'legacy' | 'multi_user';
  loggedIn: boolean;
  guestAccessEnabled?: boolean;
  passwordSet?: boolean;
  passwordChangeable?: boolean;
  setupState: 'enabled' | 'password_retained' | 'no_password' | 'bootstrap_required';
  setupRequired?: boolean;
  user?: {
    id: string;
    displayName: string;
    roles: string[];
    permissions: string[];
  } | null;
};

export const authApi = {
  async getStatus(): Promise<AuthStatusResponse> {
    const { data } = await apiClient.get<AuthStatusResponse>('/api/v1/auth/status');
    return data;
  },

  async updateSettings(
    authEnabled: boolean,
    password?: string,
    passwordConfirm?: string,
    currentPassword?: string
  ): Promise<AuthStatusResponse> {
    const body: {
      authEnabled: boolean;
      password?: string;
      passwordConfirm?: string;
      currentPassword?: string;
    } = { authEnabled };
    if (password !== undefined) {
      body.password = password;
    }
    if (passwordConfirm !== undefined) {
      body.passwordConfirm = passwordConfirm;
    }
    if (currentPassword !== undefined) {
      body.currentPassword = currentPassword;
    }
    const { data } = await apiClient.post<AuthStatusResponse>('/api/v1/auth/settings', body);
    return data;
  },

  async login(password: string, passwordConfirm?: string, identifier?: string): Promise<void> {
    const body: { password: string; passwordConfirm?: string; identifier?: string } = { password };
    if (passwordConfirm !== undefined) {
      body.passwordConfirm = passwordConfirm;
    }
    if (identifier !== undefined) {
      body.identifier = identifier;
    }
    await apiClient.post('/api/v1/auth/login', body);
  },

  async changePassword(
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string
  ): Promise<void> {
    await apiClient.post('/api/v1/auth/change-password', {
      currentPassword,
      newPassword,
      newPasswordConfirm,
    });
  },

  async logout(): Promise<void> {
    await apiClient.post('/api/v1/auth/logout');
  },

  async acceptInvitation(
    token: string,
    displayName: string,
    password: string,
    passwordConfirm: string,
  ): Promise<void> {
    await apiClient.post('/api/v1/auth/invitations/accept', {
      token,
      displayName,
      password,
      passwordConfirm,
    });
  },
};
