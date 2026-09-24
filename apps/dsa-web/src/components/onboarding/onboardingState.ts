export type OnboardingRole = 'member' | 'auditor' | 'platform_admin';
export type OnboardingScope = 'workspace' | 'admin';
export type OnboardingResult = 'completed' | 'skipped';

export const ONBOARDING_REPLAY_EVENT = 'dsa:onboarding:replay';

// v2 adds a route-aware, full-workspace tour. Existing users see the expanded
// guide once, while completion still remains scoped by user, role, and surface.
const ONBOARDING_STORAGE_PREFIX = 'dsa:onboarding:v2';

export function resolveOnboardingRole(
  roles: string[] | undefined,
  scope: OnboardingScope,
): OnboardingRole | null {
  const availableRoles = new Set(roles ?? []);

  if (scope === 'admin') {
    if (availableRoles.has('platform_owner') || availableRoles.has('platform_admin')) {
      return 'platform_admin';
    }
    if (availableRoles.has('auditor')) {
      return 'auditor';
    }
    return null;
  }

  return availableRoles.has('member') ? 'member' : null;
}

export function getOnboardingStorageKey(
  userId: string,
  role: OnboardingRole,
  scope: OnboardingScope,
): string {
  return `${ONBOARDING_STORAGE_PREFIX}:${scope}:${role}:${encodeURIComponent(userId)}`;
}

export function hasFinishedOnboarding(
  storage: Pick<Storage, 'getItem'>,
  userId: string,
  role: OnboardingRole,
  scope: OnboardingScope,
): boolean {
  try {
    return storage.getItem(getOnboardingStorageKey(userId, role, scope)) !== null;
  } catch {
    return false;
  }
}

export function finishOnboarding(
  storage: Pick<Storage, 'setItem'>,
  userId: string,
  role: OnboardingRole,
  scope: OnboardingScope,
  result: OnboardingResult,
): void {
  try {
    storage.setItem(
      getOnboardingStorageKey(userId, role, scope),
      JSON.stringify({ result, finishedAt: new Date().toISOString() }),
    );
  } catch {
    // Onboarding is optional UX. Storage restrictions must not block the app.
  }
}

export function replayOnboarding(scope: OnboardingScope): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(ONBOARDING_REPLAY_EVENT, { detail: { scope } }));
}
