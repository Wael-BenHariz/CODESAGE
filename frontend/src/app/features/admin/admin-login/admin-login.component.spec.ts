import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { AdminLoginComponent } from './admin-login.component';
import { AdminLoginError, AdminLoginService } from '../../../core/services/admin-login.service';

describe('AdminLoginComponent — /admin credential form', () => {
  let adminLogin: jasmine.SpyObj<AdminLoginService>;
  let navigateSpy: jasmine.Spy;

  beforeEach(async () => {
    adminLogin = jasmine.createSpyObj<AdminLoginService>('AdminLoginService', ['login']);
    adminLogin.login.and.returnValue(Promise.resolve());

    TestBed.configureTestingModule({
      imports: [AdminLoginComponent],
      providers: [provideRouter([]), { provide: AdminLoginService, useValue: adminLogin }]
    });

    const router = TestBed.inject(Router);
    navigateSpy = spyOn(router, 'navigate').and.returnValue(Promise.resolve(true));

    await TestBed.compileComponents();
  });

  function create(): {
    fixture: ComponentFixture<AdminLoginComponent>;
    component: AdminLoginComponent;
  } {
    const fixture = TestBed.createComponent(AdminLoginComponent);
    fixture.detectChanges();
    return { fixture, component: fixture.componentInstance };
  }

  function view(fixture: ComponentFixture<AdminLoginComponent>): HTMLElement {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('renders a labelled username/password form with one submit button', () => {
    const { fixture } = create();
    const el = view(fixture);

    expect(el.querySelector('h1')?.textContent).toContain('Platform admin');
    expect(el.querySelector('label[for="admin-username"]')).not.toBeNull();
    expect(el.querySelector('label[for="admin-password"]')).not.toBeNull();
    expect(el.querySelectorAll('input').length).toBe(2);
    expect(el.querySelector('button[type="submit"]')).not.toBeNull();
    // The form is the only action on this screen — no stray buttons.
    expect(el.querySelectorAll('button').length).toBe(1);
  });

  it('does not call the service while the form is incomplete', async () => {
    const { component } = create();

    await component.submit();

    expect(adminLogin.login).not.toHaveBeenCalled();
    expect(component.form.controls.username.touched).toBeTrue();
    expect(component.form.controls.password.touched).toBeTrue();
  });

  it('signs in and routes to the admin interface', async () => {
    const { component } = create();
    component.form.setValue({ username: ' platform-admin ', password: 'secret' });

    await component.submit();

    expect(adminLogin.login).toHaveBeenCalledWith('platform-admin', 'secret');
    expect(navigateSpy).toHaveBeenCalledWith(['/platform']);
    expect(component.error()).toBeNull();
  });

  it('keeps the user on the page and shows the failure inline', async () => {
    adminLogin.login.and.returnValue(
      Promise.reject(new AdminLoginError('Incorrect username or password.'))
    );
    const { fixture, component } = create();
    component.form.setValue({ username: 'platform-admin', password: 'nope' });

    await component.submit();
    const el = view(fixture);

    expect(component.error()).toBe('Incorrect username or password.');
    expect(navigateSpy).not.toHaveBeenCalled();
    expect(el.querySelector('[role="alert"]')?.textContent).toContain(
      'Incorrect username or password.'
    );
  });

  it('shows generic copy for an unexpected failure (never a raw payload)', async () => {
    adminLogin.login.and.returnValue(Promise.reject({ status: 500, detail: 'stack trace' }));
    const { component } = create();
    component.form.setValue({ username: 'platform-admin', password: 'secret' });

    await component.submit();

    expect(component.error()).toBe('Sign-in failed. Try again.');
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it('disables submit while pending and never double-submits', async () => {
    const { fixture, component } = create();
    component.form.setValue({ username: 'platform-admin', password: 'secret' });

    let release!: () => void;
    adminLogin.login.and.returnValue(new Promise<void>(resolve => (release = resolve)));

    const pending = component.submit();
    const button = view(fixture).querySelector('button[type="submit"]') as HTMLButtonElement;

    expect(button.disabled).toBeTrue();
    expect(button.textContent).toContain('Signing in');

    // A second click while pending is a no-op.
    void component.submit();
    expect(adminLogin.login).toHaveBeenCalledTimes(1);

    release();
    await pending;

    expect(view(fixture).querySelector('button[type="submit"]')).toBe(button);
    expect(button.disabled).toBeFalse();
    expect(navigateSpy).toHaveBeenCalledTimes(1);
  });

  it('marks invalid fields touched and shows inline errors', async () => {
    const { fixture, component } = create();

    await component.submit();
    const el = view(fixture);

    expect(el.querySelectorAll('.field-error').length).toBe(2);
    expect(el.querySelector('#admin-username')?.getAttribute('aria-invalid')).toBe('true');
    expect(el.querySelector('#admin-password')?.getAttribute('aria-invalid')).toBe('true');
  });
});
