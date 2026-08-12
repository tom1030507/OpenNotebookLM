export interface DrawerFocusableElement {
  focus: () => void;
}

interface DrawerKeyboardEvent {
  key: string;
  shiftKey: boolean;
  preventDefault: () => void;
}

export class DrawerFocusController {
  private trigger: DrawerFocusableElement | null = null;

  constructor(
    private readonly getFocusableElements: () => DrawerFocusableElement[],
    private readonly getActiveElement: () => DrawerFocusableElement | null,
  ) {}

  rememberTrigger(trigger: DrawerFocusableElement) {
    this.trigger = trigger;
  }

  focusInitialElement() {
    this.getFocusableElements()[0]?.focus();
  }

  trapTab(event: DrawerKeyboardEvent) {
    if (event.key !== 'Tab') return false;

    const focusableElements = this.getFocusableElements();
    if (focusableElements.length === 0) return false;

    const activeIndex = focusableElements.indexOf(this.getActiveElement() as DrawerFocusableElement);
    const shouldWrapBackward = event.shiftKey && activeIndex <= 0;
    const shouldWrapForward = !event.shiftKey && activeIndex === focusableElements.length - 1;
    const shouldReturnToDrawer = !event.shiftKey && activeIndex === -1;

    if (shouldWrapBackward) {
      event.preventDefault();
      focusableElements[focusableElements.length - 1]?.focus();
      return true;
    }

    if (shouldWrapForward || shouldReturnToDrawer) {
      event.preventDefault();
      focusableElements[0]?.focus();
      return true;
    }

    return false;
  }

  restoreTriggerFocus() {
    this.trigger?.focus();
    this.trigger = null;
  }
}
