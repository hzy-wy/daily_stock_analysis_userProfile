import { beforeEach, describe, expect, it } from 'vitest';
import {
  finishOnboarding,
  getOnboardingStorageKey,
  hasFinishedOnboarding,
  resolveOnboardingRole,
} from '../onboardingState';

describe('onboardingState', () => {
  beforeEach(() => localStorage.clear());

  it('maps each account role to the tour available on its real product surface', () => {
    expect(resolveOnboardingRole(['member'], 'workspace')).toBe('member');
    expect(resolveOnboardingRole(['auditor'], 'workspace')).toBeNull();
    expect(resolveOnboardingRole(['auditor'], 'admin')).toBe('auditor');
    expect(resolveOnboardingRole(['platform_admin'], 'admin')).toBe('platform_admin');
    expect(resolveOnboardingRole(['platform_owner'], 'admin')).toBe('platform_admin');
  });

  it('stores completion per user, role and surface', () => {
    finishOnboarding(localStorage, 'user/42', 'member', 'workspace', 'completed');

    expect(hasFinishedOnboarding(localStorage, 'user/42', 'member', 'workspace')).toBe(true);
    expect(hasFinishedOnboarding(localStorage, 'another-user', 'member', 'workspace')).toBe(false);
    expect(localStorage.getItem(getOnboardingStorageKey('user/42', 'member', 'workspace')))
      .toContain('completed');
  });

  it('treats an explicit skip as seen so the tour does not interrupt the next login', () => {
    finishOnboarding(localStorage, 'auditor-1', 'auditor', 'admin', 'skipped');

    expect(hasFinishedOnboarding(localStorage, 'auditor-1', 'auditor', 'admin')).toBe(true);
  });
});
