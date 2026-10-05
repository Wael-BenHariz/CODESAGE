import { TestBed, ComponentFixture } from '@angular/core/testing';
import { Type } from '@angular/core';
import { provideRouter } from '@angular/router';

import { NotFoundComponent } from './not-found/not-found.component';
import { ForbiddenComponent } from './forbidden/forbidden.component';

/**
 * Rule 5 pages. Shared contract: render a uniform message, offer a way back
 * to a route every role can open (/repositories), and stay public — an
 * anonymous visitor must never bounce to /login from here.
 */
describe('error pages', () => {
  async function create<T>(component: Type<T>): Promise<HTMLElement> {
    await TestBed.configureTestingModule({
      imports: [component],
      providers: [provideRouter([])]
    }).compileComponents();

    const fixture: ComponentFixture<T> = TestBed.createComponent(component);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  describe('NotFoundComponent (/not-found + wildcard)', () => {
    it('renders the generic 404 message with no access-denied wording', async () => {
      const el = await create(NotFoundComponent);

      expect(el.querySelector('[data-testid="not-found-page"]')).not.toBeNull();
      expect(el.textContent).toContain('404');
      expect(el.textContent).toContain('Page not found');
      // Rule: a 404 must never read as "you don't have access".
      expect(el.textContent?.toLowerCase()).not.toContain("don't have access");
      expect(el.textContent?.toLowerCase()).not.toContain('forbidden');
    });

    it('offers a route every role can read (repositories) plus home', async () => {
      const el = await create(NotFoundComponent);

      const hrefs = Array.from(el.querySelectorAll('a')).map(a => a.getAttribute('href'));
      expect(hrefs).toContain('/repositories');
      expect(hrefs).toContain('/');
    });
  });

  describe('ForbiddenComponent (guard denial target)', () => {
    it('explains the dead end as a permissions problem', async () => {
      const el = await create(ForbiddenComponent);

      expect(el.querySelector('[data-testid="forbidden-page"]')).not.toBeNull();
      expect(el.textContent).toContain('403');
      expect(el.textContent).toContain('Forbidden');
      expect(el.textContent).toContain("don't have permission");
    });

    it('links back to repositories and home', async () => {
      const el = await create(ForbiddenComponent);

      const hrefs = Array.from(el.querySelectorAll('a')).map(a => a.getAttribute('href'));
      expect(hrefs).toContain('/repositories');
      expect(hrefs).toContain('/');
    });
  });
});
