import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { KeycloakService } from 'keycloak-angular';
import { of } from 'rxjs';

import { GithubCallbackComponent } from './github-callback.component';
import { AuthService } from '../../../core/services/auth.service';
import { GithubAppService } from '../../../core/services/github-app.service';
import { environment } from '@env/environment';

describe('GithubCallbackComponent — install callback (Keycloak session)', () => {
  let github: jasmine.SpyObj<GithubAppService>;
  let navigateSpy: jasmine.Spy;
  let paramValues: Record<string, string | null>;
  let auth: AuthService;

  beforeEach(async () => {
    localStorage.removeItem(environment.userKey);
    paramValues = { success: 'true' };

    github = jasmine.createSpyObj<GithubAppService>('GithubAppService', ['getInstallStatus']);
    github.getInstallStatus.and.returnValue(of({ installed: true, installation_id: 42 }));

    TestBed.configureTestingModule({
      imports: [GithubCallbackComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: GithubAppService, useValue: github },
        // AuthService (injected by the component) depends on KeycloakService.
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

    const router = TestBed.inject(Router);
    navigateSpy = spyOn(router, 'navigate').and.returnValue(Promise.resolve(true));

    // Constructed here (no session, no cache → idle), then stubbed per test.
    auth = TestBed.inject(AuthService);
    spyOn(auth, 'isAuthenticated').and.returnValue(false);

    await TestBed.compileComponents();
  });

  it('finalizes the install when the session survived the GitHub round-trip', () => {
    (auth.isAuthenticated as jasmine.Spy).and.returnValue(true);

    const fixture = TestBed.createComponent(GithubCallbackComponent);
    fixture.detectChanges();

    expect(github.getInstallStatus).toHaveBeenCalled();
    expect(navigateSpy).toHaveBeenCalledWith(['/dashboard']);
    expect(fixture.componentInstance.state()).toBe('processing');
  });

  it('renders the status line as the page heading (Step 10 a11y)', () => {
    (auth.isAuthenticated as jasmine.Spy).and.returnValue(true);

    const fixture = TestBed.createComponent(GithubCallbackComponent);
    fixture.detectChanges();

    const heading = fixture.nativeElement.querySelector('h1.status') as HTMLElement | null;
    expect(heading).not.toBeNull();
    expect(heading?.textContent).toBe(fixture.componentInstance.statusMessage());
  });

  it('falls back to the login page when no Keycloak session exists', fakeAsync(() => {
    const fixture = TestBed.createComponent(GithubCallbackComponent);
    fixture.detectChanges();

    expect(github.getInstallStatus).not.toHaveBeenCalled();
    expect(navigateSpy).not.toHaveBeenCalledWith(['/dashboard']);

    tick(2000);
    expect(navigateSpy).toHaveBeenCalledWith(['/login'], {
      queryParams: { message: 'app_installed' }
    });
  }));

  it('shows the error state when the backend could not verify the install', () => {
    paramValues = { success: 'false' };

    const fixture = TestBed.createComponent(GithubCallbackComponent);
    fixture.detectChanges();

    expect(fixture.componentInstance.state()).toBe('error');
    expect(fixture.componentInstance.statusMessage()).toContain('could not be verified');
    expect(github.getInstallStatus).not.toHaveBeenCalled();
    expect(navigateSpy).not.toHaveBeenCalled();
  });
});
