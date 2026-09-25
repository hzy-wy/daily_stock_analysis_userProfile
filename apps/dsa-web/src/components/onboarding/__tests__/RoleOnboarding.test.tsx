import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminOnboarding, WorkspaceOnboarding } from '../RoleOnboarding';
import { finishOnboarding, replayOnboarding } from '../onboardingState';

const mockAuth = {
  loggedIn: true,
  guestMode: false,
  user: {
    id: 'member-1',
    displayName: '测试用户',
    roles: ['member'],
    permissions: ['workspace.use'],
  },
};

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => mockAuth,
}));

describe('WorkspaceOnboarding', () => {
  beforeEach(() => {
    localStorage.clear();
    mockAuth.loggedIn = true;
    mockAuth.guestMode = false;
    mockAuth.user.id = 'member-1';
    vi.restoreAllMocks();
  });

  it('appears automatically once and stays dismissed on the next mount', async () => {
    const first = render(
      <MemoryRouter initialEntries={['/']}>
        <WorkspaceOnboarding />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: '先完成一次真实的投研动作' }, { timeout: 1600 }))
      .toBeInTheDocument();
    const skipButtons = screen.getAllByRole('button', { name: '跳过导览' });
    fireEvent.click(skipButtons[skipButtons.length - 1]);
    await waitFor(() => expect(screen.queryByTestId('guided-tour')).not.toBeInTheDocument());
    first.unmount();

    render(
      <MemoryRouter initialEntries={['/']}>
        <WorkspaceOnboarding />
      </MemoryRouter>,
    );
    await new Promise((resolve) => window.setTimeout(resolve, 650));

    expect(screen.queryByTestId('guided-tour')).not.toBeInTheDocument();
  });

  it('shows an isolated member tour to a guest session and remembers its completion separately', async () => {
    mockAuth.loggedIn = false;
    mockAuth.guestMode = true;
    render(
      <MemoryRouter initialEntries={['/']}>
        <WorkspaceOnboarding />
      </MemoryRouter>,
    );
    expect(await screen.findByRole('heading', { name: '先完成一次真实的投研动作' }, { timeout: 1600 }))
      .toBeInTheDocument();
    const skipButtons = screen.getAllByRole('button', { name: '跳过导览' });
    fireEvent.click(skipButtons[skipButtons.length - 1]);
    await waitFor(() => expect(screen.queryByTestId('guided-tour')).not.toBeInTheDocument());

    expect(localStorage.getItem('dsa:onboarding:v2:workspace:member:guest-session')).not.toBeNull();
    expect(localStorage.getItem('dsa:onboarding:v2:workspace:member:member-1')).toBeNull();
  });

  it('allows a member to replay a previously finished tour on demand', async () => {
    finishOnboarding(localStorage, 'member-1', 'member', 'workspace', 'completed');
    render(
      <MemoryRouter initialEntries={['/']}>
        <WorkspaceOnboarding />
      </MemoryRouter>,
    );

    replayOnboarding('workspace');

    expect(await screen.findByRole('heading', { name: '先完成一次真实的投研动作' }))
      .toBeInTheDocument();
  });

  it('moves the full workspace tour to the route owned by the next module', async () => {
    const RouteProbe = () => {
      const location = useLocation();
      return <output data-testid="tour-route">{location.pathname}</output>;
    };
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <WorkspaceOnboarding />
        <RouteProbe />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('heading', { name: '先完成一次真实的投研动作' }, { timeout: 1600 }))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '下一步' }));

    await waitFor(() => expect(screen.getByTestId('tour-route').textContent).toBe('/'));
  });

  it('shows the auditor-specific read-only flow in the admin surface', async () => {
    render(
      <AdminOnboarding
        user={{
          id: 'auditor-1',
          displayName: '审计用户',
          roles: ['auditor'],
          permissions: ['admin.access', 'audit.read'],
        }}
      />,
    );

    expect(await screen.findByRole('heading', { name: '你的任务是核对，不是修改' }, { timeout: 1600 }))
      .toBeInTheDocument();
  });

  it('uses the platform-administrator flow for the protected owner role', async () => {
    render(
      <AdminOnboarding
        user={{
          id: 'owner-1',
          displayName: '平台所有者',
          roles: ['platform_owner'],
          permissions: ['*'],
        }}
      />,
    );

    expect(await screen.findByRole('heading', { name: '先掌握三项管理职责' }, { timeout: 1600 }))
      .toBeInTheDocument();
  });
});
