import { RefObject, useEffect, useRef } from 'react';

interface UseDialogFocusOptions {
  isOpen: boolean;
  onClose: () => void;
  dismissible?: boolean;
  initialFocusRef: RefObject<HTMLElement | null>;
}

export default function useDialogFocus({
  isOpen,
  onClose,
  dismissible = true,
  initialFocusRef,
}: UseDialogFocusOptions) {
  const triggerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const dismissibleRef = useRef(dismissible);

  onCloseRef.current = onClose;
  dismissibleRef.current = dismissible;

  useEffect(() => {
    if (!isOpen) return;

    triggerRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && dismissibleRef.current) {
        event.preventDefault();
        onCloseRef.current();
      }
    };

    initialFocusRef.current?.focus();

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      triggerRef.current?.focus();
    };
  }, [initialFocusRef, isOpen]);
}
