import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet } from '@angular/router';

import { ToastContainerComponent } from './shared/components/toast/toast-container.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, ToastContainerComponent],
  template: '<router-outlet></router-outlet><app-toast-container></app-toast-container>',
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
      }
    `
  ]
})
export class AppComponent {}
