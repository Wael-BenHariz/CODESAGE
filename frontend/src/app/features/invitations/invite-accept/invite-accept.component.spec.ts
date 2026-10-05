import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { KeycloakService } from 'keycloak-angular';
import { of, throwError } from 'rxjs';

import { InviteAcceptComponent } from './invite-accept.component';
import { ApiError } from '../../../core/services/api.service';
import { AuthService } from '../../../core/services/auth.service';
import { InvitationService } from '../../../core/services/invitation.service';
import { InvitationPreview } from '../../../core/models/invitation.model';
import { User } from '../../../core/models/user.model';
import { environment } from '@env/environment';

describe('InviteAcceptComponent — public invite landing (plan Step 12)', () => {
  let fixture: ComponentFixture<InviteAcceptComponent>;
  let invitations: jasmine.SpyObj<InvitationService>;
  let auth: AuthService;
  let paramValues: Record<string, string | null>;

  const preview: InvitationPreview = {
    org_name: 'acme',
    role: 'REVIEWER',
    email_masked: 'jo***@example.com'
  };

  const user = (email: string): User => ({
    id: 'u-1',
    login: 'octocat',
    email,
    name: null,
    avatarUrl: '',
    createdAt: '2026-01-01',
    updatedAt: '2026-01-01'
  });

  beforeEach(async () => {
    localStorage.removeItem(environment.userKey);
    paramValues = { token: 'tok-abc' };

    invitations = jasmine.createSpyObj<InvitationService>('InvitationService', [
      'preview',
      'accept'
    ]);

    TestBed.configureTestingModule({
      imports: [InviteAcceptComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: InvitationService, useValue: invitations },
        {
          provide: KeycloakService,
          useValue: jasmine.createSpyObj<KeycloakService>('KeycloakService', ['isLoggedIn'])
        },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: {
                get: (key: string): string | null => paramValues[key] ?? null
              }
            }
          }
        }
      ]
    });

    auth = TestBed.inject(AuthService);
    spyOn(auth, 'isAuthenticated').and.returnValue(false);
    spyOn(auth, 'login');
    spyOn(auth, 'switchAccount');

    await TestBed.compileComponents();
  });

  function create(): ComponentFixture<InviteAcceptComponent> {
    fixture = TestBed.createComponent(InviteAcceptComponent);
    fixture.detectChanges(); // ngOnInit → preview
    return fixture;
  }

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

  // --- loading / states -------------------------------------------------------

  it('shows the friendly invalid state when the token is missing (no API call)', () => {
    paramValues = {};

    create();

    expect(invitations.preview).not.toHaveBeenCalled();
    expect(fixture.componentInstance.state()).toBe('invalid');
    expect(q('invite-invalid')).not.toBeNull();
  });

  it('maps a 404 preview to the same friendly invalid state (no enumeration)', () => {
    invitations.preview.and.returnValue(
      throwError(() => new ApiError('Invitation not found', 404, 'Invitation not found'))
    );

    create();

    expect(fixture.componentInstance.state()).toBe('invalid');
    const text = el().textContent ?? '';
    expect(text).toContain('invalid, expired, or has already been used');
    expect(q('invite-signin')).toBeNull();
    expect(q('invite-accept-btn')).toBeNull();
  });

  it('offers a retry for a transient preview failure (non-404)', () => {
    invitations.preview.and.returnValue(throwError(() => new ApiError('boom', 500, undefined)));

    create();
    expect(fixture.componentInstance.state()).toBe('error');
    expect(q('invite-load-error')).not.toBeNull();

    invitations.preview.and.returnValue(of(preview));
    click('invite-retry');

    expect(invitations.preview).toHaveBeenCalledTimes(2);
    expect(fixture.componentInstance.state()).toBe('ready');
    expect(q('invite-preview')).not.toBeNull();
  });

  // --- signed-out flow --------------------------------------------------------

  it('previews publicly, asks a signed-out visitor to sign in — and returns to this URL', () => {
    invitations.preview.and.returnValue(of(preview));

    create();

    expect(el().textContent).toContain('acme');
    expect(q('invite-org')?.textContent).toContain('acme');
    expect(q('invite-role')?.textContent).toContain('REVIEWER');
    expect(q('invite-masked-email')?.textContent).toContain('jo***@example.com');
    // Never auto-accept — there is no session to accept with anyway.
    expect(invitations.accept).not.toHaveBeenCalled();
    expect(q('invite-signin')).not.toBeNull();

    click('invite-signin');
    expect(auth.login).toHaveBeenCalledWith(TestBed.inject(Router).url);
  });

  // --- signed-in flow ---------------------------------------------------------

  it('never auto-accepts: an explicit click accepts and lands on the joined state', () => {
    (auth.isAuthenticated as jasmine.Spy).and.returnValue(true);
    spyOn(auth, 'currentUser').and.returnValue(user('jo@example.com'));
    invitations.preview.and.returnValue(of(preview));
    invitations.accept.and.returnValue(
      of({ org_id: 'org-1', org_name: 'acme', role: 'REVIEWER', email_mismatch: false })
    );

    create();
    expect(q('invite-accept-btn')).not.toBeNull();
    expect(invitations.accept).not.toHaveBeenCalled(); // explicit action only

    click('invite-accept-btn');

    expect(invitations.accept).toHaveBeenCalledWith('tok-abc');
    expect(fixture.componentInstance.state()).toBe('joined');
    expect(q('invite-joined')).not.toBeNull();
    expect(q('invite-joined-role')?.textContent).toContain('REVIEWER');
    expect(q('invite-mismatch-note')).toBeNull();
  });

  it('blocks on email mismatch with Continue anyway / switch account before accepting', () => {
    (auth.isAuthenticated as jasmine.Spy).and.returnValue(true);
    spyOn(auth, 'currentUser').and.returnValue(user('jane@other.com'));
    invitations.preview.and.returnValue(of(preview));
    invitations.accept.and.returnValue(
      of({ org_id: 'org-1', org_name: 'acme', role: 'REVIEWER', email_mismatch: true })
    );

    create();

    expect(q('invite-mismatch')).not.toBeNull();
    expect(q('invite-accept-btn')).toBeNull(); // nothing happens implicitly

    click('invite-switch');
    expect(auth.switchAccount).toHaveBeenCalledWith(TestBed.inject(Router).url);
    expect(invitations.accept).not.toHaveBeenCalled();

    click('invite-continue');
    expect(q('invite-accept-btn')).not.toBeNull();

    click('invite-accept-btn');
    expect(invitations.accept).toHaveBeenCalledTimes(1);
    // The authoritative server flag lands as a note on the joined state.
    expect(q('invite-mismatch-note')).not.toBeNull();
  });

  it('shows the exact backend reason when the token was already used (409)', () => {
    (auth.isAuthenticated as jasmine.Spy).and.returnValue(true);
    spyOn(auth, 'currentUser').and.returnValue(user('jo@example.com'));
    invitations.preview.and.returnValue(of(preview));
    invitations.accept.and.returnValue(
      throwError(() => new ApiError('Invitation already used', 409, 'Invitation already used'))
    );

    create();
    click('invite-accept-btn');

    expect(q('invite-accept-error')?.textContent).toContain('Invitation already used');
    // Button re-enabled for a retry (a fresh token, not this one).
    const button = q('invite-accept-btn') as HTMLButtonElement;
    expect(button.disabled).toBeFalse();
    expect(fixture.componentInstance.state()).toBe('ready');
  });
});
