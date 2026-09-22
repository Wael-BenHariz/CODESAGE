import { Component, input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-avatar',
  standalone: true,
  imports: [CommonModule],
  template: `
    <img
      [src]="src()"
      [alt]="alt()"
      class="avatar"
      [style.width.px]="size()"
      [style.height.px]="size()"
    />
  `,
  styles: [
    `
      .avatar {
        border-radius: 50%;
        object-fit: cover;
      }
    `
  ]
})
export class AvatarComponent {
  src = input.required<string>();
  alt = input<string>('User avatar');
  size = input<number>(32);
}
