import { Injectable, signal } from '@angular/core';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

/** Visible lifetime per kind — errors linger so they can be read. */
const TTL_MS: Record<ToastKind, number> = {
  success: 4000,
  info: 5000,
  error: 8000
};

/**
 * Minimal toast/snackbar for mutation feedback (plan Step 1, rule 6:
 * every mutation shows a visible success or error message).
 *
 * Messages are plain text rendered through interpolation only — API error
 * detail is untrusted content and must never reach `innerHTML`.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly _toasts = signal<Toast[]>([]);
  readonly toasts = this._toasts.asReadonly();

  private seq = 0;

  show(kind: ToastKind, message: string): number {
    const id = ++this.seq;
    this._toasts.update(list => [...list, { id, kind, message }]);
    setTimeout(() => this.dismiss(id), TTL_MS[kind]);
    return id;
  }

  success(message: string): number {
    return this.show('success', message);
  }

  error(message: string): number {
    return this.show('error', message);
  }

  info(message: string): number {
    return this.show('info', message);
  }

  dismiss(id: number): void {
    this._toasts.update(list => list.filter(toast => toast.id !== id));
  }
}
