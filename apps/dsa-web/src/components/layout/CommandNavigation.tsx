import type React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  BarChart3,
  Bell,
  BriefcaseBusiness,
  Ellipsis,
  Gauge,
  Home,
  LogOut,
  Search,
  Settings2,
  Sparkles,
} from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import { ALPHASIFT_CONFIG_CHANGED_EVENT, SYSTEM_CONFIG_CHANGED_EVENT, alphasiftApi } from '../../api/alphasift';
import { useAuth } from '../../contexts/AuthContext';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { Drawer } from '../common/Drawer';
import { UiLanguageToggle } from '../i18n/UiLanguageToggle';
import { ThemeToggle } from '../theme/ThemeToggle';

type NavItem = {
  key: string;
  labelKey: UiTextKey;
  to: string;
  icon: React.ComponentType<{ className?: string }>;
  exact?: boolean;
};

const PRIMARY_NAV_ITEMS: NavItem[] = [
  { key: 'home', labelKey: 'layout.nav.home', to: '/', icon: Home, exact: true },
  { key: 'screening', labelKey: 'layout.nav.screening', to: '/screening', icon: Search },
  { key: 'portfolio', labelKey: 'layout.nav.portfolio', to: '/portfolio', icon: BriefcaseBusiness },
  { key: 'decision-signals', labelKey: 'layout.nav.decisionSignals', to: '/decision-signals', icon: Activity },
  { key: 'backtest', labelKey: 'layout.nav.backtest', to: '/backtest', icon: BarChart3 },
];

const SECONDARY_NAV_ITEMS: NavItem[] = [
  { key: 'alerts', labelKey: 'layout.nav.alerts', to: '/alerts', icon: Bell },
  { key: 'usage', labelKey: 'layout.nav.usage', to: '/usage', icon: Gauge },
  { key: 'settings', labelKey: 'layout.nav.settings', to: '/settings', icon: Settings2 },
];

type NavigationLinkProps = {
  item: NavItem;
  mode: 'desktop' | 'dock' | 'menu';
  onNavigate?: () => void;
};

const NavigationLink: React.FC<NavigationLinkProps> = ({ item, mode, onNavigate }) => {
  const { t } = useUiLanguage();
  const label = t(item.labelKey);
  const Icon = item.icon;

  return (
    <NavLink
      to={item.to}
      end={item.exact}
      onClick={onNavigate}
      role={mode === 'menu' ? 'menuitem' : undefined}
      aria-label={label}
      className={({ isActive }) => cn(
        mode === 'desktop' && 'command-nav-link',
        mode === 'dock' && 'mobile-dock-link',
        mode === 'menu' && 'command-menu-link',
        isActive && mode === 'desktop' && 'command-nav-link--active',
        isActive && mode === 'dock' && 'mobile-dock-link--active',
        isActive && mode === 'menu' && 'command-menu-link--active',
      )}
    >
      <Icon className={cn(mode === 'menu' ? 'h-[18px] w-[18px]' : 'h-[17px] w-[17px]')} />
      <span>{label}</span>
    </NavLink>
  );
};

export const CommandNavigation: React.FC = () => {
  const { authEnabled, logout } = useAuth();
  const { t } = useUiLanguage();
  const location = useLocation();
  const desktopMenuRef = useRef<HTMLDivElement | null>(null);
  const [showAlphaSiftNav, setShowAlphaSiftNav] = useState(false);
  const [desktopMenuOpen, setDesktopMenuOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  useEffect(() => {
    let active = true;

    const refreshAlphaSiftStatus = async () => {
      try {
        const status = await alphasiftApi.getStatus();
        if (active) {
          setShowAlphaSiftNav(status.enabled);
        }
      } catch {
        if (active) {
          setShowAlphaSiftNav(false);
        }
      }
    };

    void refreshAlphaSiftStatus();
    window.addEventListener(ALPHASIFT_CONFIG_CHANGED_EVENT, refreshAlphaSiftStatus);
    window.addEventListener(SYSTEM_CONFIG_CHANGED_EVENT, refreshAlphaSiftStatus);

    return () => {
      active = false;
      window.removeEventListener(ALPHASIFT_CONFIG_CHANGED_EVENT, refreshAlphaSiftStatus);
      window.removeEventListener(SYSTEM_CONFIG_CHANGED_EVENT, refreshAlphaSiftStatus);
    };
  }, []);

  useEffect(() => {
    if (!desktopMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (desktopMenuRef.current && !desktopMenuRef.current.contains(event.target as Node)) {
        setDesktopMenuOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setDesktopMenuOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [desktopMenuOpen]);

  const primaryItems = useMemo(
    () => showAlphaSiftNav
      ? PRIMARY_NAV_ITEMS
      : PRIMARY_NAV_ITEMS.filter((item) => item.key !== 'screening'),
    [showAlphaSiftNav],
  );
  const dockItems = useMemo(() => primaryItems.slice(0, 4), [primaryItems]);
  const isSecondaryRoute = SECONDARY_NAV_ITEMS.some((item) => location.pathname.startsWith(item.to));
  const closeMobileMenu = () => setMobileMenuOpen(false);
  const requestLogout = () => {
    setDesktopMenuOpen(false);
    setMobileMenuOpen(false);
    setShowLogoutConfirm(true);
  };

  return (
    <>
      <header className="app-commandbar" data-testid="app-commandbar">
        <div className="app-commandbar__surface">
          <NavLink to="/" className="app-commandbar__brand" aria-label={t('layout.appFallbackTitle')}>
            <span className="app-commandbar__brand-mark" aria-hidden="true">
              <BarChart3 className="h-5 w-5" />
              <span className="app-commandbar__brand-pulse" />
            </span>
            <span className="app-commandbar__brand-copy">
              <strong>DSA</strong>
              <small>{t('layout.productSubtitle')}</small>
            </span>
          </NavLink>

          <nav className="app-commandbar__nav" aria-label={t('layout.mainNav')}>
            {primaryItems.map((item) => (
              <NavigationLink key={item.key} item={item} mode="desktop" />
            ))}

            <div className="app-commandbar__more" ref={desktopMenuRef}>
              <button
                type="button"
                onClick={() => setDesktopMenuOpen((value) => !value)}
                className={cn('command-nav-link', isSecondaryRoute && 'command-nav-link--active')}
                data-state={desktopMenuOpen ? 'open' : 'closed'}
                aria-haspopup="menu"
                aria-expanded={desktopMenuOpen}
                aria-label={t('layout.more')}
              >
                <Ellipsis className="h-[17px] w-[17px]" />
                <span>{t('layout.more')}</span>
              </button>

              {desktopMenuOpen ? (
                <div className="command-menu" role="menu" aria-label={t('layout.systemMenu')}>
                  <div className="command-menu__eyebrow">
                    <Sparkles className="h-3.5 w-3.5" />
                    {t('layout.workspaceTools')}
                  </div>
                  {SECONDARY_NAV_ITEMS.map((item) => (
                    <NavigationLink
                      key={item.key}
                      item={item}
                      mode="menu"
                      onNavigate={() => setDesktopMenuOpen(false)}
                    />
                  ))}
                  {authEnabled ? (
                    <button type="button" onClick={requestLogout} className="command-menu-link command-menu-link--danger">
                      <LogOut className="h-[18px] w-[18px]" />
                      <span>{t('layout.logout')}</span>
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </nav>

          <div className="app-commandbar__utilities" aria-label={t('layout.utilityNav')}>
            <span className="app-commandbar__status" aria-hidden="true">
              <span />
              DSA LIVE
            </span>
            <div className="app-commandbar__utility">
              <UiLanguageToggle triggerClassName="app-commandbar__utility-button" />
            </div>
            <div className="app-commandbar__utility">
              <ThemeToggle triggerClassName="app-commandbar__utility-button" />
            </div>
            <button
              type="button"
              className="app-commandbar__mobile-menu-button"
              onClick={() => setMobileMenuOpen(true)}
              aria-label={t('layout.openNav')}
            >
              <Ellipsis className="h-5 w-5" />
            </button>
          </div>
        </div>
      </header>

      <nav className="app-mobile-dock" aria-label={t('layout.mobileDock')}>
        {dockItems.map((item) => (
          <NavigationLink key={item.key} item={item} mode="dock" />
        ))}
        <button
          type="button"
          className={cn('mobile-dock-link', isSecondaryRoute && 'mobile-dock-link--active')}
          onClick={() => setMobileMenuOpen(true)}
          aria-label={t('layout.more')}
        >
          <Ellipsis className="h-[17px] w-[17px]" />
          <span>{t('layout.more')}</span>
        </button>
      </nav>

      <Drawer
        isOpen={mobileMenuOpen}
        onClose={closeMobileMenu}
        title={t('layout.systemMenu')}
        width="max-w-sm"
        zIndex={92}
        side="right"
        backdropClassName="app-command-drawer__backdrop"
      >
        <div className="command-drawer">
          <div className="command-drawer__identity">
            <span className="app-commandbar__brand-mark" aria-hidden="true"><BarChart3 className="h-5 w-5" /></span>
            <div>
              <strong>DSA</strong>
              <p>{t('layout.productSubtitle')}</p>
            </div>
          </div>
          <nav className="command-drawer__links" aria-label={t('layout.navMenu')}>
            {[...primaryItems, ...SECONDARY_NAV_ITEMS].map((item) => (
              <NavigationLink key={item.key} item={item} mode="menu" onNavigate={closeMobileMenu} />
            ))}
          </nav>
          {authEnabled ? (
            <button type="button" onClick={requestLogout} className="command-menu-link command-menu-link--danger mt-3 w-full">
              <LogOut className="h-[18px] w-[18px]" />
              <span>{t('layout.logout')}</span>
            </button>
          ) : null}
        </div>
      </Drawer>

      <ConfirmDialog
        isOpen={showLogoutConfirm}
        title={t('layout.logoutTitle')}
        message={t('layout.logoutMessage')}
        confirmText={t('layout.logoutConfirm')}
        cancelText={t('common.cancel')}
        isDanger
        onConfirm={() => {
          setShowLogoutConfirm(false);
          void logout();
        }}
        onCancel={() => setShowLogoutConfirm(false)}
      />
    </>
  );
};
