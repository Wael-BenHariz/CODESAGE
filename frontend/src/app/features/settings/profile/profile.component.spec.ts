import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal, WritableSignal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { KeycloakService } from 'keycloak-angular';

import { ProfileComponent } from './profile.component';
import { AuthService } from '../../../core/services/auth.service';
import { User } from '../../../core/models/user.model';

describe('ProfileComponent — personal profile (plan Step 4)', () => {
  let fixture: ComponentFixture<ProfileComponent>;
  let component: ProfileComponent;
  let auth: {
    currentUser: WritableSignal<User | null>;
    updateProfile: jasmine.Spy;
    logout: jasmine.Spy;
  };

  const user: User = {
    id: 'u-1',
    login: 'octocat',
    email: 'octo@example.com',
    name: 'Octo Cat',
    avatarUrl: 'https://example.com/a.png',
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
    role: 'DEVELOPER'
  };

  beforeEach(async () => {
    auth = {
      currentUser: signal<User | null>(user),
      updateProfile: jasmine.createSpy('updateProfile').and.returnValue(of({ ...user })),
      logout: jasmine.createSpy('logout')
    };

    await TestBed.configureTestingModule({
      imports: [ProfileComponent],
      providers: [
        provideHttpClient(),
        provideRouter([]),
        { provide: AuthService, useValue: auth },
        {
          provide: KeycloakService,
          useValue: jasmine.createSpyObj<KeycloakService>('KeycloakService', ['isLoggedIn'])
        }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    fixture.detectChanges(); // ngOnInit → syncFromUser
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  it('seeds the drafts from the session profile and stays clean until edited', () => {
    expect(component.nameDraft()).toBe('Octo Cat');
    expect(component.emailDraft()).toBe('octo@example.com');
    expect(component.dirty()).toBeFalse();
    expect(component.canSave()).toBeFalse();
  });

  it('shows identity fields read-only with an explanation', () => {
    const login = el().querySelector('#profile-login') as HTMLInputElement;
    expect(login.disabled).toBeTrue();
    expect(login.value).toBe('octocat');
    expect(el().textContent).toContain('Managed by your GitHub account');
  });

  it('saves name and email through PATCH /users/me and marks the state saved', () => {
    component.onNameInput({ target: { value: 'New Name' } } as unknown as Event);
    component.onEmailInput({ target: { value: 'new@example.com' } } as unknown as Event);
    fixture.detectChanges();

    expect(component.dirty()).toBeTrue();
    component.save();

    expect(auth.updateProfile).toHaveBeenCalledWith({ name: 'New Name', email: 'new@example.com' });
    expect(component.saving()).toBeFalse();
    expect(component.saved()).toBeTrue();
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="profile-saved"]')).not.toBeNull();
  });

  it('rejects an invalid email before any request', () => {
    component.onEmailInput({ target: { value: 'not-an-email' } } as unknown as Event);
    component.save();

    expect(auth.updateProfile).not.toHaveBeenCalled();
    expect(component.saveError()).toContain('valid email');
  });

  it('surfaces a failed save visibly and keeps the edits for retry', () => {
    auth.updateProfile.and.returnValue(throwError(() => new Error('save failed')));
    component.onNameInput({ target: { value: 'Retry Me' } } as unknown as Event);
    component.save();

    expect(component.saveError()).toContain('save failed');
    expect(component.saved()).toBeFalse();
    expect(component.nameDraft()).toBe('Retry Me');
  });

  it('discards drafts back to the loaded profile (never mid-save)', () => {
    component.onNameInput({ target: { value: 'Discard Me' } } as unknown as Event);
    component.reset();
    expect(component.nameDraft()).toBe('Octo Cat');
    expect(component.dirty()).toBeFalse();
  });

  it('never sends identity-provider fields — only name and email', () => {
    component.onNameInput({ target: { value: 'X' } } as unknown as Event);
    component.save();
    const payload = auth.updateProfile.calls.mostRecent().args[0] as Record<string, unknown>;
    expect(Object.keys(payload).sort()).toEqual(['email', 'name']);
  });

  it('routes the logout button through AuthService', () => {
    (
      el().querySelector('[data-testid="profile-danger-zone"] .btn-danger') as HTMLButtonElement
    ).click();
    expect(auth.logout).toHaveBeenCalled();
  });
});
