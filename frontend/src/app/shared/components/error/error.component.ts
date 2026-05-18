import { Component, input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-error',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="error-message">
      <span class="error-icon">⚠️</span>
      <span class="error-text">{{ message() }}</span>
    </div>
  `,
  styles: [`
    .error-message {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      background: #fed7d7;
      border-radius: 6px;
      color: #c53030;
    }
    .error-icon {
      font-size: 18px;
    }
  `]
})
export class ErrorComponent {
  message = input<string>('An error occurred');
}