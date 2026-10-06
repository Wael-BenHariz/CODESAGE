import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { HelpComponent } from './help.component';

describe('HelpComponent (plan Step 9)', () => {
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HelpComponent],
      providers: [provideRouter([])]
    }).compileComponents();
    const fixture = TestBed.createComponent(HelpComponent);
    fixture.detectChanges();
    el = fixture.nativeElement as HTMLElement;
  });

  function q(selector: string): HTMLElement | null {
    return el.querySelector(selector);
  }

  function text(selector: string): string {
    return (q(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  it('renders every planned section with its testid', () => {
    for (const id of [
      'help-pipeline',
      'help-severity',
      'help-roles',
      'help-posting',
      'help-invite',
      'help-glossary'
    ]) {
      expect(q(`[data-testid="${id}"]`)).not.toBeNull();
    }
  });

  it('describes the real pipeline: webhook → parallel analysis → agents → summary → post/stage', () => {
    const svg = q('.pipeline-svg');
    expect(svg?.getAttribute('role')).toBe('img');
    expect(svg?.getAttribute('aria-label')).toContain('Review pipeline');
    expect(el.querySelectorAll('.pipeline-svg rect.pipe-box').length).toBe(5);

    const steps = Array.from(el.querySelectorAll('.pipeline-steps .step-card'));
    expect(steps.length).toBe(5);
    const body = text('.pipeline-steps');
    expect(body).toContain('webhook');
    expect(body).toContain('synchronized');
    expect(body).toContain('SonarQube and Semgrep scan the changes in parallel');
    expect(body).toContain('test-coverage agents');
    expect(body).toContain('strongest severity');
  });

  it('lays out the five-step severity scale with meaning and action', () => {
    for (const level of ['critical', 'high', 'medium', 'low', 'info']) {
      expect(q(`[data-testid="sev-${level}"]`)).not.toBeNull();
    }
    const critical = text('[data-testid="sev-critical"]');
    expect(critical).toContain('Security holes');
    expect(critical).toContain('Fix before merging.');
    // Both vocabularies are reconciled in plain words — never implied identical.
    expect(text('[data-testid="help-severity"] .help-note')).toContain(
      'error = critical, warning = medium, suggestion = low'
    );
  });

  it('mirrors the documented role matrix plus the read-only sentinel', () => {
    for (const id of ['platform-admin', 'org-admin', 'reviewer', 'developer', 'none']) {
      expect(q(`[data-testid="role-${id}"]`)).not.toBeNull();
    }
    expect(text('[data-testid="role-developer"]')).toContain('dismiss and restore findings');
    expect(text('[data-testid="role-none"]')).toContain('403');
    expect(text('[data-testid="help-roles"] .help-note')).toContain('never downgrades');
  });

  it('contrasts staged and automatic posting without inventing behaviour', () => {
    expect(text('[data-testid="posting-auto"]')).toContain('posted to the pull request');
    const staged = text('[data-testid="posting-staged"]');
    expect(staged).toContain('ready to post');
    expect(staged).toContain('never posted twice');
  });

  it('keeps invitations inside the documented role range', () => {
    const steps = el.querySelectorAll('[data-testid="help-invite"] li');
    expect(steps.length).toBe(4);
    const body = text('[data-testid="help-invite"]');
    expect(body).toContain('Members & invitations');
    expect(body).toContain('Developer or Reviewer');
    expect(body).toContain('cannot grant admin roles');
    expect(body).toContain('never downgraded');
  });

  it('defines the four planned glossary terms, including the verdict vocabulary', () => {
    for (const id of ['cwe', 'owasp', 'false-positive', 'dismissed-validated']) {
      expect(q(`[data-testid="term-${id}"]`)).not.toBeNull();
    }
    expect(text('[data-testid="help-glossary"]')).toContain('CWE-89');
    expect(text('[data-testid="help-glossary"]')).toContain('Top Ten');
    const dismissed = q('[data-testid="term-dismissed-validated"]')?.nextElementSibling
      ?.textContent;
    expect(dismissed).toContain('confirmed, false positive, or needs investigation');
    expect(dismissed).toContain('Status filter');
  });

  it('links only home — no external or invented URLs on a static page', () => {
    expect(q('[data-testid="help-back"]')?.getAttribute('href')).toBe('/');
    expect(el.querySelectorAll('a[href^="http"]').length).toBe(0);
  });
});
