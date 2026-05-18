import { Component, input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-diff-view',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './diff-view.component.html',
  styleUrl: './diff-view.component.scss'
})
export class DiffViewComponent {
  files = input.required<any[]>();
}