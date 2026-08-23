import {
  clearSession,
  isCurrentSessionCredential,
  type SessionCredentialSnapshot,
} from './session';

let retireAccountState: (() => void) | null = null;

/**
 * Lets the store provide its synchronous account reset without making the API
 * client import Zustand and create an API/store dependency cycle.
 */
export const registerAccountStateRetirer = (retirer: () => void): void => {
  retireAccountState = retirer;
};

/**
 * Retire only the session that sent the rejected credential. A late response
 * from a previous account must not clear a newer account's token or workspace.
 */
export const retireCurrentSession = (
  snapshot: SessionCredentialSnapshot,
): boolean => {
  if (!isCurrentSessionCredential(snapshot)) {
    return false;
  }

  retireAccountState?.();
  clearSession();
  return true;
};
