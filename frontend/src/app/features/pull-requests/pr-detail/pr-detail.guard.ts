import { CanDeactivateFn } from '@angular/router';

/**
 * Plan Step 4 — dirty-state warning when leaving: navigating away from the
 * PR page while the review panel's summary editor holds unsaved changes
 * asks for confirmation (window.confirm — same channel as the editor's own
 * cancel button). Tab close / reload is covered separately by the panel's
 * `window:beforeunload` listener.
 *
 * Typed structurally (not against `PrDetailComponent`) so importing this
 * guard from the routes file never drags the lazy-loaded PR page into the
 * main bundle.
 */
export const confirmUnsavedSummaryGuard: CanDeactivateFn<{
  hasUnsavedSummaryEdit(): boolean;
}> = component =>
  component?.hasUnsavedSummaryEdit()
    ? window.confirm('You have unsaved summary changes. Leave this page?')
    : true;
