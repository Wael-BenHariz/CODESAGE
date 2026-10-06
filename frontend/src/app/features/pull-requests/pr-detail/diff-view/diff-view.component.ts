import { Component, input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DiffFile } from '../../../../core/models/pull-request.model';

/**
 * File-level diff list (plan Step 7 housekeeping).
 *
 * Type is now `DiffFile[]` — the exact wire shape (`path`/`filename`/
 * `status`/counts) — instead of `any[]`. The component stays UNWIRED: the
 * backend exposes no changed-files/diff endpoint for a PR yet (gap in
 * docs/BACKEND_GAPS_FOR_UI.md), and the Monaco integration it was built for
 * has not landed, so nothing feeds it.
 */
@Component({
  selector: 'app-diff-view',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './diff-view.component.html',
  styleUrl: './diff-view.component.scss'
})
export class DiffViewComponent {
  files = input.required<DiffFile[]>();
}
