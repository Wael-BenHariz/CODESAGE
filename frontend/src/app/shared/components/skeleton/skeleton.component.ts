import { Component, input } from '@angular/core';

/**
 * Skeleton placeholder — the shimmer-free (flat surface + pulse) loading
 * block used while a section's data is on the wire. Purely decorative
 * (aria-hidden); the surrounding region should carry aria-busy.
 */
@Component({
  selector: 'app-skeleton',
  standalone: true,
  template: `
    <span
      class="skeleton"
      [style.width]="width()"
      [style.height]="height()"
      [style.border-radius]="radius()"
      aria-hidden="true"
      [attr.data-testid]="testid() || null"
    ></span>
  `,
  styles: [
    `
      .skeleton {
        display: block;
        background: var(--surface-2);
        border-radius: var(--radius-sm);
        animation: pulse 1.6s ease-in-out infinite;
      }
    `
  ]
})
export class SkeletonComponent {
  width = input('100%');
  height = input('16px');
  radius = input('var(--radius-sm)');
  testid = input('');
}
