import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { AdminStatus } from '../../api/admin';
import { GuidedTour } from './GuidedTour';
import { getOnboardingCopy, type OnboardingStep } from './onboardingContent';
import {
  ONBOARDING_REPLAY_EVENT,
  finishOnboarding,
  hasFinishedOnboarding,
  resolveOnboardingRole,
  type OnboardingResult,
  type OnboardingScope,
} from './onboardingState';

type TourUser = NonNullable<AdminStatus['user']>;

const GUEST_TOUR_USER: TourUser = {
  id: 'guest-session',
  displayName: '游客',
  roles: ['member'],
  permissions: [],
};

type RoleTourProps = {
  scope: OnboardingScope;
  user: TourUser;
  autoStart: boolean;
  onStepChange?: (step: OnboardingStep) => void;
};

const RoleTour: React.FC<RoleTourProps> = ({ scope, user, autoStart, onStepChange }) => {
  const { language } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const role = resolveOnboardingRole(user.roles, scope);
  const canConfigureSystem = user.permissions.includes('*') || user.permissions.includes('system.configure');
  const copy = useMemo(
    () => role ? getOnboardingCopy(role, language, { includeSettings: canConfigureSystem }) : null,
    [canConfigureSystem, language, role],
  );

  useEffect(() => {
    if (!role || !autoStart || typeof window === 'undefined') return undefined;
    if (hasFinishedOnboarding(window.localStorage, user.id, role, scope)) return undefined;
    const timer = window.setTimeout(() => setIsOpen(true), 320);
    return () => window.clearTimeout(timer);
  }, [autoStart, role, scope, user.id]);

  useEffect(() => {
    const handleReplay = (event: Event) => {
      const detail = (event as CustomEvent<{ scope?: OnboardingScope }>).detail;
      if (detail?.scope === scope && role) setIsOpen(true);
    };
    window.addEventListener(ONBOARDING_REPLAY_EVENT, handleReplay);
    return () => window.removeEventListener(ONBOARDING_REPLAY_EVENT, handleReplay);
  }, [role, scope]);

  const handleClose = useCallback((result: OnboardingResult) => {
    setIsOpen(false);
    if (role) finishOnboarding(window.localStorage, user.id, role, scope, result);
  }, [role, scope, user.id]);

  if (!role || !copy) return null;
  return (
    <GuidedTour
      isOpen={isOpen}
      language={language}
      roleLabel={copy.roleLabel}
      steps={copy.steps}
      onClose={handleClose}
      onStepChange={onStepChange}
    />
  );
};

export const WorkspaceOnboarding: React.FC = () => {
  const { loggedIn, guestMode, user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const handleStepChange = useCallback((step: OnboardingStep) => {
    if (step.route && location.pathname !== step.route) {
      navigate(step.route);
    }
  }, [location.pathname, navigate]);

  const tourUser = guestMode ? GUEST_TOUR_USER : loggedIn ? user : null;
  if (!tourUser) return null;
  return <RoleTour scope="workspace" user={tourUser} autoStart onStepChange={handleStepChange} />;
};

export const AdminOnboarding: React.FC<{ user: TourUser }> = ({ user }) => (
  <RoleTour scope="admin" user={user} autoStart />
);
