import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';

import { confirmUnsavedSummaryGuard } from './pr-detail.guard';

/**
 * Plan Step 4 — dirty-state warning when leaving (in-app navigation half;
 * tab close/reload is the panel's beforeunload listener).
 */
describe('confirmUnsavedSummaryGuard', () => {
  const route = null as unknown as ActivatedRouteSnapshot; // not exercised
  const state = null as unknown as RouterStateSnapshot;

  it('allows leaving without asking when nothing is unsaved', () => {
    const confirmSpy = spyOn(window, 'confirm');

    const allowed = confirmUnsavedSummaryGuard(
      { hasUnsavedSummaryEdit: () => false },
      route,
      state,
      state
    );

    expect(allowed).toBeTrue();
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('allows leaving when there is no panel at all (component absent)', () => {
    const confirmSpy = spyOn(window, 'confirm');

    const allowed = confirmUnsavedSummaryGuard(undefined as never, route, state, state);

    expect(allowed).toBeTrue();
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('asks before leaving a dirty edit and blocks when declined', () => {
    const confirmSpy = spyOn(window, 'confirm').and.returnValue(false);

    const allowed = confirmUnsavedSummaryGuard(
      { hasUnsavedSummaryEdit: () => true },
      route,
      state,
      state
    );

    expect(confirmSpy).toHaveBeenCalledWith('You have unsaved summary changes. Leave this page?');
    expect(allowed).toBeFalse();
  });

  it('leaves when the user confirms discarding the edit', () => {
    spyOn(window, 'confirm').and.returnValue(true);

    const allowed = confirmUnsavedSummaryGuard(
      { hasUnsavedSummaryEdit: () => true },
      route,
      state,
      state
    );

    expect(allowed).toBeTrue();
  });
});
