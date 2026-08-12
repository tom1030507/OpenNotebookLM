import { RefObject, useEffect, useRef } from 'react';

interface UseDialogFocusOptions {
  isOpen: boolean;
  onClose: () => void;
  dismissible?: boolean;
  dialogRef: RefObject<HTMLElement | null>;
  initialFocusRef: RefObject<HTMLElement | null>;
}

const dialogStack: symbol[] = [];
const focusableSelector = [
  'a[href]',
  'button',
  'input',
  'select',
  'textarea',
  'iframe',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const isRadio = (element: HTMLElement): element is HTMLInputElement => (
  element instanceof HTMLInputElement && element.type === 'radio'
);

const isVisible = (element: HTMLElement) => {
  for (let current: HTMLElement | null = element; current; current = current.parentElement) {
    if (current.hidden || current.getAttribute('aria-hidden') === 'true') return false;

    const styles = window.getComputedStyle(current);
    if (styles.display === 'none' || styles.visibility === 'hidden') return false;
  }

  return true;
};

export const getTabbableElements = (dialog: HTMLElement) => {
  const candidates = Array
    .from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
    .filter((element) => !element.matches(':disabled') && isVisible(element));

  // A radio group occupies a single tab stop: the checked radio, or the first
  // one when the group has no selection yet.
  return candidates.filter((element) => {
    if (!isRadio(element)) return true;

    const group = candidates.filter((candidate) => (
      isRadio(candidate) && candidate.name === element.name
    )) as HTMLInputElement[];

    return (group.find((radio) => radio.checked) ?? group[0]) === element;
  });
};

export default function useDialogFocus({
  isOpen,
  onClose,
  dismissible = true,
  dialogRef,
  initialFocusRef,
}: UseDialogFocusOptions) {
  const triggerRef = useRef<HTMLElement | null>(null);
  const dialogIdRef = useRef<symbol>(Symbol('dialog'));
  const onCloseRef = useRef(onClose);
  const dismissibleRef = useRef(dismissible);

  onCloseRef.current = onClose;
  dismissibleRef.current = dismissible;

  useEffect(() => {
    const dialog = dialogRef.current;
    const dialogId = dialogIdRef.current;
    if (!isOpen || !dialog) return;

    triggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    dialogStack.push(dialogId);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (dialogStack.at(-1) !== dialogId) return;

      if (event.key === 'Escape' && dismissibleRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== 'Tab') return;

      const tabbableElements = getTabbableElements(dialog);
      if (tabbableElements.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = tabbableElements[0];
      const last = tabbableElements[tabbableElements.length - 1];
      const activeElement = document.activeElement;
      const isFocusOutsideDialog = !dialog.contains(activeElement);

      if (event.shiftKey && (activeElement === first || isFocusOutsideDialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (activeElement === last || isFocusOutsideDialog)) {
        event.preventDefault();
        first.focus();
      }
    };

    initialFocusRef.current?.focus();
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      const wasTopmost = dialogStack.at(-1) === dialogId;
      const stackIndex = dialogStack.lastIndexOf(dialogId);
      if (stackIndex !== -1) dialogStack.splice(stackIndex, 1);

      if (wasTopmost && triggerRef.current?.isConnected) {
        triggerRef.current.focus();
      }
    };
  }, [dialogRef, initialFocusRef, isOpen]);
}
