import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { of, throwError } from 'rxjs';

import { OrgInvitationsComponent } from './org-invitations.component';
import { ApiError } from '../../../core/services/api.service';
import { InvitationService } from '../../../core/services/invitation.service';
import { OrgInvitation } from '../../../core/models/invitation.model';

describe('OrgInvitationsComponent — invite form, list, revoke (plan Step 12)', () => {
  let fixture: ComponentFixture<OrgInvitationsComponent>;
  let invitations: jasmine.SpyObj<InvitationService>;

  const pending: OrgInvitation = {
    id: 'inv-1',
    email: 'teammate@example.com',
    role: 'DEVELOPER',
    status: 'pending',
    expires_at: '2026-10-12T10:00:00Z',
    created_at: '2026-10-05T10:00:00Z',
    invited_by: 'octocat'
  };

  beforeEach(() => {
    invitations = jasmine.createSpyObj<InvitationService>('InvitationService', [
      'list',
      'create',
      'revoke'
    ]);
    invitations.list.and.returnValue(of([pending]));

    TestBed.configureTestingModule({
      imports: [OrgInvitationsComponent],
      providers: [{ provide: InvitationService, useValue: invitations }]
    });

    fixture = TestBed.createComponent(OrgInvitationsComponent);
    fixture.componentRef.setInput('orgId', 'org-1');
    fixture.detectChanges(); // ngOnInit → list
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function q(testId: string): HTMLElement | null {
    return el().querySelector(`[data-testid="${testId}"]`);
  }

  function click(testId: string): void {
    const node = q(testId);
    expect(node).withContext(`expected [data-testid="${testId}"] to render`).not.toBeNull();
    node?.click();
    fixture.detectChanges();
  }

  function typeEmail(value: string): void {
    const input = fixture.debugElement.query(By.css('[data-testid="invite-email"]'));
    input.nativeElement.value = value;
    input.nativeElement.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  it('lists invitations with email, role, status and inviter', () => {
    expect(invitations.list).toHaveBeenCalledWith('org-1');
    const text = el().textContent ?? '';
    expect(text).toContain('teammate@example.com');
    expect(text).toContain('DEVELOPER');
    expect(text).toContain('pending');
    expect(text).toContain('octocat');
    expect(q('invite-revoke')).not.toBeNull(); // pending rows are revocable
  });

  it('creates an invitation with the selected role and confirms', () => {
    invitations.create.and.returnValue(of({ ...pending, email: 'new@example.com' }));

    typeEmail('new@example.com');
    const select = fixture.debugElement.query(By.css('[data-testid="invite-role"]'));
    select.nativeElement.value = 'REVIEWER';
    select.nativeElement.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    click('invite-send');

    expect(invitations.create).toHaveBeenCalledWith('org-1', {
      email: 'new@example.com',
      role: 'REVIEWER'
    });
    expect(q('invite-sent')?.textContent).toContain('Invitation created for new@example.com');
    // Dev notes (mail_console / pod log) stay out of the UI (plan Step 7).
    expect(q('invite-sent')?.textContent).not.toContain('console');
    expect(invitations.list).toHaveBeenCalledTimes(2); // refreshed after the create
  });

  it('disables the send button while the email is empty', () => {
    const button = q('invite-send') as HTMLButtonElement;
    expect(button.disabled).toBeTrue();
    typeEmail('someone@example.com');
    expect((q('invite-send') as HTMLButtonElement).disabled).toBeFalse();
  });

  it('surfaces the rate-limit message on 429', () => {
    invitations.create.and.returnValue(
      throwError(
        () => new ApiError('Invitation rate limit reached (20 per hour per org).', 429, 'detail')
      )
    );

    typeEmail('someone@example.com');
    click('invite-send');

    expect(q('invite-form-error')?.textContent).toContain('rate limit');
    expect(fixture.componentInstance.sending()).toBeFalse();
    expect(q('invite-sent')).toBeNull();
  });

  it('revokes a pending invitation locally after 204', () => {
    invitations.revoke.and.returnValue(of(undefined));

    click('invite-revoke');

    expect(invitations.revoke).toHaveBeenCalledWith('org-1', 'inv-1');
    expect(fixture.componentInstance.items()[0].status).toBe('revoked');
    expect(q('invite-revoke')).toBeNull(); // pending-only action
  });

  it('keeps the row and shows the backend detail when revoke hits 409', () => {
    invitations.revoke.and.returnValue(
      throwError(
        () =>
          new ApiError(
            'Invitation already accepted — remove the member instead.',
            409,
            'Invitation already accepted — remove the member instead.'
          )
      )
    );

    click('invite-revoke');

    expect(q('invite-revoke-error')?.textContent).toContain('already accepted');
    expect(fixture.componentInstance.items()[0].status).toBe('pending');
  });

  it('renders the list read-only when the caller cannot manage invitations', () => {
    fixture.componentRef.setInput('canManage', false);
    fixture.detectChanges();

    expect(el().textContent).toContain('teammate@example.com');
    expect(q('invite-send')).toBeNull();
    expect(q('invite-revoke')).toBeNull();
  });

  it('offers a retry when the list fails to load', () => {
    invitations.list.and.returnValue(throwError(() => new ApiError('boom', 500, undefined)));

    const retryFixture = TestBed.createComponent(OrgInvitationsComponent);
    retryFixture.componentRef.setInput('orgId', 'org-1');
    retryFixture.detectChanges();

    const retryEl = retryFixture.nativeElement as HTMLElement;
    expect(retryEl.querySelector('[data-testid="invites-load-error"]')).not.toBeNull();

    invitations.list.and.returnValue(of([pending]));
    const retryButton = retryEl.querySelector<HTMLButtonElement>(
      '[data-testid="invites-load-error"] button'
    );
    retryButton?.click();
    retryFixture.detectChanges();

    expect(invitations.list).toHaveBeenCalledTimes(3); // initial + failed + retry
    expect(retryEl.textContent).toContain('teammate@example.com');
  });
});
