import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/services/auth.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss'
})
export class SettingsComponent {
  private readonly auth = inject(AuthService);

  user = this.auth.currentUser;
  isSaving = signal(false);

  saveSettings(): void {
    this.isSaving.set(true);
    setTimeout(() => this.isSaving.set(false), 1000);
  }

  logout(): void {
    this.auth.logout();
  }
}
