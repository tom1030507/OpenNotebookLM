import { describe, expect, it } from 'vitest';
import { DrawerFocusController } from './drawerFocusController';

class FocusScope {
  activeElement: FocusTarget | null = null;

  constructor(readonly focusableElements: FocusTarget[]) {}
}

class FocusTarget {
  constructor(private readonly scope: FocusScope) {}

  focus() {
    this.scope.activeElement = this;
  }
}

describe('DrawerFocusController', () => {
  it('moves focus to the drawer close control and restores the invoking trigger on dismissal', () => {
    const scope = new FocusScope([]);
    const trigger = new FocusTarget(scope);
    const closeControl = new FocusTarget(scope);
    scope.focusableElements.push(closeControl);
    scope.activeElement = trigger;
    const controller = new DrawerFocusController(
      () => scope.focusableElements,
      () => scope.activeElement,
    );

    controller.rememberTrigger(trigger);
    controller.focusInitialElement();
    expect(scope.activeElement).toBe(closeControl);

    controller.restoreTriggerFocus();
    expect(scope.activeElement).toBe(trigger);
  });

  it('wraps Tab and Shift+Tab within the drawer focusable elements', () => {
    const scope = new FocusScope([]);
    const first = new FocusTarget(scope);
    const last = new FocusTarget(scope);
    scope.focusableElements.push(first, last);
    const controller = new DrawerFocusController(
      () => scope.focusableElements,
      () => scope.activeElement,
    );
    let prevented = false;

    scope.activeElement = last;
    controller.trapTab({
      key: 'Tab',
      shiftKey: false,
      preventDefault: () => {
        prevented = true;
      },
    });
    expect(prevented).toBe(true);
    expect(scope.activeElement).toBe(first);

    prevented = false;
    scope.activeElement = first;
    controller.trapTab({
      key: 'Tab',
      shiftKey: true,
      preventDefault: () => {
        prevented = true;
      },
    });
    expect(prevented).toBe(true);
    expect(scope.activeElement).toBe(last);

    const backgroundControl = new FocusTarget(scope);
    prevented = false;
    scope.activeElement = backgroundControl;
    controller.trapTab({
      key: 'Tab',
      shiftKey: false,
      preventDefault: () => {
        prevented = true;
      },
    });
    expect(prevented).toBe(true);
    expect(scope.activeElement).toBe(first);
  });
});
