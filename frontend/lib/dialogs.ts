import { create } from 'zustand';

/**
 * In-app replacements for window.confirm and window.prompt (#237).
 *
 * The native dialogs ignored the theme, could not be styled or translated,
 * and blocked the whole page. These keep the same call shape — await an
 * answer where the code used to read one — and DialogHost renders them.
 */

interface ConfirmRequest {
  id: number;
  kind: 'confirm';
  title: string;
  message?: string;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  resolve: (confirmed: boolean) => void;
}

interface TextRequest {
  id: number;
  kind: 'text';
  title: string;
  label: string;
  initialValue: string;
  confirmLabel: string;
  resolve: (value: string | null) => void;
}

export type DialogRequest = ConfirmRequest | TextRequest;

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

interface DialogState {
  active: DialogRequest | null;
}

export const useDialogRequests = create<DialogState>(() => ({ active: null }));

let nextId = 0;

// A second request replaces the first, which is answered as cancelled: two
// questions stacked on top of each other would leave one of them unreachable.
const open = (request: DistributiveOmit<DialogRequest, 'id'>) => {
  const previous = useDialogRequests.getState().active;
  if (previous?.kind === 'confirm') previous.resolve(false);
  if (previous?.kind === 'text') previous.resolve(null);
  nextId += 1;
  useDialogRequests.setState({ active: { ...request, id: nextId } as DialogRequest });
};

/** Close the active dialog with an answer; DialogHost calls this. */
export const settleDialog = (answer: boolean | string | null) => {
  const { active } = useDialogRequests.getState();
  if (!active) return;
  useDialogRequests.setState({ active: null });
  if (active.kind === 'confirm') active.resolve(answer === true);
  else active.resolve(typeof answer === 'string' ? answer : null);
};

/**
 * Ask the reader to confirm an action.
 *
 * @returns true when confirmed, false when cancelled or dismissed.
 */
export const confirmAction = (options: {
  title: string;
  message?: string;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
}): Promise<boolean> => new Promise((resolve) => {
  open({ kind: 'confirm', ...options, resolve });
});

/**
 * Ask the reader for one line of text, such as a new name.
 *
 * @returns the entered text, trimmed, or null when cancelled or left empty.
 */
export const askText = (options: {
  title: string;
  label: string;
  initialValue?: string;
  confirmLabel: string;
}): Promise<string | null> => new Promise((resolve) => {
  open({
    kind: 'text',
    initialValue: '',
    ...options,
    resolve: (value) => resolve(value?.trim() ? value.trim() : null),
  });
});
