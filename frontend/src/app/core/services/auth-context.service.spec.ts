import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of, throwError } from 'rxjs';

import { AuthContextService } from './auth-context.service';
import { AuthService } from './auth.service';
import { OrgSettingsService, OrgSummary } from './org-settings.service';

const ORG_KEY = 'codesage_active_org';

describe('AuthContextService', () => {
  let authUser: ReturnType<typeof signal<{ role: string } | null>>;
  let orgSvc: jasmine.SpyObj<OrgSettingsService>;
  let ctx: AuthContextService;

  const org = (id: string, role: string, name = id): OrgSummary => ({
    id,
    name,
    account_type: 'Organization',
    role
  });

  beforeEach(() => {
    localStorage.removeItem(ORG_KEY);
    authUser = signal<{ role: string } | null>(null);
    orgSvc = jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs']);
    orgSvc.listOrgs.and.returnValue(of([]));

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { currentUser: authUser } },
        { provide: OrgSettingsService, useValue: orgSvc }
      ]
    });
    ctx = TestBed.inject(AuthContextService);
  });

  afterEach(() => {
    localStorage.removeItem(ORG_KEY);
  });

  describe('can() — mirrors the backend guards (cosmetic only)', () => {
    it('gives every authenticated context read access, NONE included', () => {
      authUser.set({ role: 'NONE' });
      expect(ctx.can('read')).toBeTrue();

      authUser.set({ role: 'DEVELOPER' });
      expect(ctx.can('read')).toBeTrue();
    });

    it('keeps NONE read-only even with an ORG_ADMIN membership row (NONE-first)', async () => {
      authUser.set({ role: 'NONE' });
      orgSvc.listOrgs.and.returnValue(of([org('o1', 'ORG_ADMIN', 'acme')]));
      await ctx.ensureOrgs();

      expect(ctx.can('write')).toBeFalse();
      expect(ctx.can('validate')).toBeFalse();
      expect(ctx.can('org:settings')).toBeFalse();
      expect(ctx.can('platform')).toBeFalse();
    });

    it('lets DEVELOPER write but not validate or manage settings', () => {
      authUser.set({ role: 'DEVELOPER' });

      expect(ctx.can('write')).toBeTrue();
      expect(ctx.can('validate')).toBeFalse();
      expect(ctx.can('org:settings')).toBeFalse();
      expect(ctx.can('platform')).toBeFalse();
    });

    it('lets REVIEWER validate (effective role reaches REVIEWER)', () => {
      authUser.set({ role: 'REVIEWER' });

      expect(ctx.can('validate')).toBeTrue();
      expect(ctx.can('org:settings')).toBeFalse();
      expect(ctx.can('platform')).toBeFalse();
    });

    it('lets ORG_ADMIN manage org settings but not platform settings', () => {
      authUser.set({ role: 'ORG_ADMIN' });

      expect(ctx.can('org:settings')).toBeTrue();
      expect(ctx.can('platform')).toBeFalse();
    });

    it('restricts platform checks to PLATFORM_ADMIN', () => {
      authUser.set({ role: 'ORG_ADMIN' });
      expect(ctx.can('platform')).toBeFalse();

      authUser.set({ role: 'PLATFORM_ADMIN' });
      expect(ctx.can('platform')).toBeTrue();
    });

    it('fails closed on an unknown or missing backend role', () => {
      authUser.set({ role: 'SOME_OTHER_ROLE' });
      expect(ctx.can('write')).toBeFalse();
      expect(ctx.can('org:settings')).toBeFalse();

      // No profile yet: the role degrades to the NONE read-only sentinel —
      // reads stay open (ANY_ROLE includes NONE), mutations stay closed.
      authUser.set(null);
      expect(ctx.can('write')).toBeFalse();
      expect(ctx.can('read')).toBeTrue();
    });

    it('applies org-membership elevation (effective = max(JWT, org_members))', async () => {
      authUser.set({ role: 'DEVELOPER' });
      orgSvc.listOrgs.and.returnValue(of([org('o1', 'ORG_ADMIN', 'acme')]));
      await ctx.ensureOrgs();

      expect(ctx.can('validate')).toBeTrue();
      expect(ctx.can('org:settings')).toBeTrue();
      expect(ctx.can('platform')).toBeFalse();
    });
  });

  describe('ensureOrgs()', () => {
    it('loads once and caches the result (header + guard share one fetch)', async () => {
      orgSvc.listOrgs.and.returnValue(of([org('o1', 'DEVELOPER')]));

      const first = await ctx.ensureOrgs();
      const second = await ctx.ensureOrgs();

      expect(first.length).toBe(1);
      expect(second).toBe(first);
      expect(orgSvc.listOrgs).toHaveBeenCalledTimes(1);
      expect(ctx.orgs()?.length).toBe(1);
    });

    it('rejects and resets the cache on error so the next call retries', async () => {
      orgSvc.listOrgs.and.returnValue(throwError(() => new Error('network down')));

      await expectAsync(ctx.ensureOrgs()).toBeRejected();

      orgSvc.listOrgs.and.returnValue(of([org('o1', 'DEVELOPER')]));
      const retried = await ctx.ensureOrgs();
      expect(retried.length).toBe(1);
      expect(orgSvc.listOrgs).toHaveBeenCalledTimes(2);
    });

    it('drops a stored org selection the caller no longer belongs to', async () => {
      localStorage.setItem(ORG_KEY, 'org-left');
      orgSvc.listOrgs.and.returnValue(of([org('org-new', 'DEVELOPER', 'fresh')]));

      await ctx.ensureOrgs();

      expect(ctx.activeOrg()?.id).toBe('org-new');
      expect(localStorage.getItem(ORG_KEY)).toBe('org-new');
    });
  });

  describe('active org switcher', () => {
    it('persists the selection to localStorage (an id, never a token)', async () => {
      orgSvc.listOrgs.and.returnValue(of([org('a', 'DEVELOPER'), org('b', 'ORG_ADMIN', 'beta')]));
      await ctx.ensureOrgs();

      ctx.setActiveOrg('b');

      expect(ctx.activeOrg()?.id).toBe('b');
      expect(localStorage.getItem(ORG_KEY)).toBe('b');
    });
  });

  describe('backendRole', () => {
    it('reports the role from GET /auth/me and null before the profile loads', () => {
      expect(ctx.backendRole()).toBeNull();

      authUser.set({ role: 'ORG_ADMIN' });
      expect(ctx.backendRole()).toBe('ORG_ADMIN');
    });
  });
});

/**
 * Storage restore needs a *fresh* injector (the signal initializer reads
 * localStorage at construction), so it runs in its own describe — TestBed
 * resets between top-level describes.
 */
describe('AuthContextService — storage restore', () => {
  afterEach(() => {
    localStorage.removeItem(ORG_KEY);
  });

  it('restores a previously stored selection on construction', () => {
    localStorage.setItem(ORG_KEY, 'remembered');

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { currentUser: signal<{ role: string } | null>(null) } },
        {
          provide: OrgSettingsService,
          useValue: jasmine.createSpyObj<OrgSettingsService>('OrgSettingsService', ['listOrgs'])
        }
      ]
    });
    const fresh = TestBed.inject(AuthContextService);

    expect(fresh.activeOrgId()).toBe('remembered');
  });
});
