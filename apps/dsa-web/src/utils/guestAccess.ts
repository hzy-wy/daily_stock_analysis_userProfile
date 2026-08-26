export const GUEST_SESSION_STORAGE_KEY = 'dsa_guest_session';
export const LOGIN_REQUIRED_EVENT = 'dsa:login-required';

export function isGuestSessionActive(): boolean {
  return typeof sessionStorage !== 'undefined'
    && sessionStorage.getItem(GUEST_SESSION_STORAGE_KEY) === 'active';
}

export function setGuestSessionActive(active: boolean): void {
  if (typeof sessionStorage === 'undefined') return;
  if (active) {
    sessionStorage.setItem(GUEST_SESSION_STORAGE_KEY, 'active');
  } else {
    sessionStorage.removeItem(GUEST_SESSION_STORAGE_KEY);
  }
}

export function dispatchLoginRequired(reason?: string): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(LOGIN_REQUIRED_EVENT, {
    detail: { reason: reason?.trim() || undefined },
  }));
}
