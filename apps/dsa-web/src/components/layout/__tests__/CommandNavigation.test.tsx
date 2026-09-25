import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandNavigation } from '../CommandNavigation';

const mockLogout = vi.fn().mockResolvedValue(undefined);
const mockGetAlphaSiftStatus = vi.fn().mockResolvedValue({ enabled: false, available: false, installSpecIsDefault: false });
const mockAuth = {
  authEnabled: true,
  guestMode: false,
  loggedIn: true,
  logout: mockLogout,
  requestLogin: vi.fn(),
  user: { roles: ['member'], permissions: ['*'] },
};

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => mockAuth,
}));

vi.mock('../../../api/alphasift', () => ({
  ALPHASIFT_CONFIG_CHANGED_EVENT: 'alphasift-config-changed',
  SYSTEM_CONFIG_CHANGED_EVENT: 'dsa-system-config-changed',
  alphasiftApi: {
    getStatus: () => mockGetAlphaSiftStatus(),
  },
}));

vi.mock('../../theme/ThemeToggle', () => ({
  ThemeToggle: () => <button type="button" aria-label="切换主题">主题</button>,
}));

vi.mock('../../i18n/UiLanguageToggle', () => ({
  UiLanguageToggle: () => <button type="button" aria-label="切换界面语言">语言</button>,
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockAuth.guestMode = false;
  mockAuth.loggedIn = true;
  mockAuth.user = { roles: ['member'], permissions: ['*'] };
  mockGetAlphaSiftStatus.mockResolvedValue({ enabled: false, available: false, installSpecIsDefault: false });
});

describe('CommandNavigation', () => {
  it('keeps primary destinations in the top command bar and interface utilities out of the nav list', () => {
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <CommandNavigation />
      </MemoryRouter>,
    );

    const commandbar = screen.getByTestId('app-commandbar');
    expect(commandbar).toContainElement(screen.getAllByRole('link', { name: '首页' })[0]);
    expect(commandbar).toContainElement(screen.getAllByRole('link', { name: '持仓' })[0]);
    expect(screen.getByRole('button', { name: '切换主题' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '切换界面语言' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '问股' })).not.toBeInTheDocument();
  });

  it('shows screening only when AlphaSift is enabled and refreshes on config changes', async () => {
    mockGetAlphaSiftStatus
      .mockResolvedValueOnce({ enabled: false, available: false, installSpecIsDefault: false })
      .mockResolvedValueOnce({ enabled: true, available: false, installSpecIsDefault: false });

    render(
      <MemoryRouter initialEntries={['/']}>
        <CommandNavigation />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('link', { name: '选股' })).not.toBeInTheDocument();
    window.dispatchEvent(new Event('dsa-system-config-changed'));

    expect((await screen.findAllByRole('link', { name: '选股' })).length).toBeGreaterThan(0);
    await waitFor(() => expect(mockGetAlphaSiftStatus.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it('moves alerts, usage and settings into the compact workspace menu', () => {
    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <CommandNavigation />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('link', { name: '告警' })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: '更多' })[0]);

    expect(screen.getByRole('menu', { name: '工作台菜单' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '告警' })).toHaveAttribute('href', '/alerts');
    expect(screen.getByRole('menuitem', { name: '用量' })).toHaveAttribute('href', '/usage');
    expect(screen.getByRole('menuitem', { name: '设置' })).toHaveAttribute('href', '/settings');
  });

  it('keeps logout behind confirmation inside the workspace menu', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <CommandNavigation />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getAllByRole('button', { name: '更多' })[0]);
    fireEvent.click(screen.getByRole('button', { name: '退出' }));
    fireEvent.click(await screen.findByRole('button', { name: '确认退出' }));

    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it('shows the onboarding replay action to a guest session', () => {
    mockAuth.guestMode = true;
    mockAuth.loggedIn = false;

    render(
      <MemoryRouter initialEntries={['/']}>
        <CommandNavigation />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getAllByRole('button', { name: '更多' })[0]);
    expect(screen.getByRole('button', { name: '新手导览' })).toBeInTheDocument();
  });
});
