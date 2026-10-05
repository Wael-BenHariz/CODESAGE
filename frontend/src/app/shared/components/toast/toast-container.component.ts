import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ToastService } from '../../../core/services/toast.service';

/**
 * Global toast stack (plan Step 1). Rendered once by AppComponent.
 * Messages interpolate as text — API payloads are untrusted and never
 * reach `innerHTML`.
 */
@Component({
  selector: 'app-toast-container',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './toast-container.component.html',
  styleUrl: './toast-container.component.scss'
})
export class ToastContainerComponent {
  readonly toast = inject(ToastService);
}
