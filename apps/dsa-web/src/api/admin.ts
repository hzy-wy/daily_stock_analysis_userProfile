import apiClient from './index';

export type AdminUser = {
  id: string;
  identifier: string | null;
  displayName: string;
  status: string;
  roles: string[];
  lastLoginAt: string | null;
  createdAt: string | null;
};

export type AdminStatus = {
  authMode: 'legacy' | 'multi_user';
  loggedIn: boolean;
  user: {
    id: string;
    displayName: string;
    roles: string[];
    permissions: string[];
  } | null;
};

export type AuditLogItem = {
  id: number;
  actorType: string;
  actorId: string | null;
  action: string;
  resourceType: string | null;
  resourceId: string | null;
  outcome: string;
  createdAt: string;
};

export const adminApi = {
  async getStatus(): Promise<AdminStatus> {
    const { data } = await apiClient.get<AdminStatus>('/api/v1/admin/auth/status');
    return data;
  },

  async login(identifier: string, password: string): Promise<void> {
    await apiClient.post('/api/v1/admin/auth/login', { identifier, password });
  },

  async logout(): Promise<void> {
    await apiClient.post('/api/v1/admin/auth/logout');
  },

  async listUsers(): Promise<AdminUser[]> {
    const { data } = await apiClient.get<{ users: AdminUser[] }>('/api/v1/admin/users');
    return data.users;
  },

  async listAuditLogs(): Promise<AuditLogItem[]> {
    const { data } = await apiClient.get<{ items: AuditLogItem[] }>('/api/v1/admin/audit-logs');
    return data.items;
  },

  async invite(identifier: string, role: string): Promise<{ token: string; expiresAt: string }> {
    const { data } = await apiClient.post<{ token: string; expiresAt: string }>(
      '/api/v1/admin/invitations',
      { identifier, role },
    );
    return data;
  },

  async updateStatus(userId: string, status: string): Promise<void> {
    await apiClient.put(`/api/v1/admin/users/${encodeURIComponent(userId)}/status`, { status });
  },

  async updateRole(userId: string, role: string): Promise<void> {
    await apiClient.put(`/api/v1/admin/users/${encodeURIComponent(userId)}/role`, { role });
  },
};
