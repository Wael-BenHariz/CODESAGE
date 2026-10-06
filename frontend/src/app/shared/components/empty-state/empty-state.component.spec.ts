import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { EmptyStateComponent } from './empty-state.component';

@Component({
  standalone: true,
  imports: [EmptyStateComponent],
  template: `
    <app-empty-state [title]="title" [message]="message" testid="repos-empty">
      <button type="button">Refresh</button>
    </app-empty-state>
  `
})
class HostComponent {
  title = 'No repositories yet';
  message = 'Watch a repository to start collecting reviews.';
}

describe('EmptyStateComponent', () => {
  let fixture: ComponentFixture<HostComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
    fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
  });

  function root(): HTMLElement {
    return fixture.nativeElement.querySelector('app-empty-state .empty');
  }

  it('renders title and message in words (never icon-only)', () => {
    expect(root().textContent).toContain('No repositories yet');
    expect(root().textContent).toContain('Watch a repository to start collecting reviews.');
    const icon = root().querySelector('.icon') as HTMLElement;
    expect(icon.getAttribute('aria-hidden')).toBe('true');
  });

  it('binds the caller testid onto the state root', () => {
    expect(root().getAttribute('data-testid')).toBe('repos-empty');
  });

  it('projects action content and hides the message slot when empty', () => {
    const action = root().querySelector('button') as HTMLButtonElement;
    expect(action.textContent).toContain('Refresh');

    fixture.componentInstance.message = '';
    fixture.detectChanges();
    expect(root().querySelector('.message')).toBeNull();
    expect(root().textContent).toContain('No repositories yet');
  });
});
