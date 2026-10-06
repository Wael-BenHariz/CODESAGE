import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { SeverityBadgeComponent } from '../../shared/components/severity-badge/severity-badge.component';
import {
  GLOSSARY_COPY,
  INVITE_STEPS,
  PIPELINE_STEPS,
  POSTING_COPY,
  ROLE_COPY,
  ROLE_NOTE,
  SEVERITY_COPY,
  SEVERITY_SCALE_NOTE
} from '../../shared/help.copy';

/**
 * /help — the public "how it works" guide (plan §4.5): pipeline diagram,
 * severity meanings, the role matrix, staged vs automatic posting, how to
 * invite, and the glossary. Every string comes from `shared/help.copy.ts`,
 * the same constants the contextual "?" popovers render, and the page holds
 * no dynamic data at all — nothing here can go stale against the API.
 */
@Component({
  selector: 'app-help',
  standalone: true,
  imports: [RouterLink, SeverityBadgeComponent],
  templateUrl: './help.component.html',
  styleUrl: './help.component.scss'
})
export class HelpComponent {
  readonly pipelineSteps = PIPELINE_STEPS;
  readonly severities = SEVERITY_COPY;
  readonly scaleNote = SEVERITY_SCALE_NOTE;
  readonly roles = ROLE_COPY;
  readonly roleNote = ROLE_NOTE;
  readonly posting = POSTING_COPY;
  readonly inviteSteps = INVITE_STEPS;
  readonly glossary = GLOSSARY_COPY;

  /** Accessible name of the diagram — titles only, details live in the list. */
  readonly diagramLabel = `Review pipeline: ${PIPELINE_STEPS.map(step => step.title).join(' → ')}`;

  /** x of step `index`'s box in the SVG viewBox (0 0 760 150). */
  boxX(index: number): number {
    return 5 + index * 155;
  }

  /** Arrowhead polygon points after step `index` (points toward the next box). */
  arrowHead(index: number): string {
    const tip = this.boxX(index) + 154;
    return `${tip},75 ${tip - 6},71 ${tip - 6},79`;
  }
}
