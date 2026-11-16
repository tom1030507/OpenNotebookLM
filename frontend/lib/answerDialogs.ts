import { settleDialog, useDialogRequests } from './dialogs';

/**
 * Test helper: answer every in-app dialog as soon as it opens, the way tests
 * used to stub window.confirm and window.prompt. Tests about the dialog itself
 * render DialogHost and click instead.
 *
 * @param text What a text question receives.
 * @returns A function that stops answering.
 */
export const answerDialogs = (
  { confirm = true, text = null }: { confirm?: boolean; text?: string | null } = {},
): (() => void) => useDialogRequests.subscribe(({ active }) => {
  if (active) settleDialog(active.kind === 'confirm' ? confirm : text);
});
