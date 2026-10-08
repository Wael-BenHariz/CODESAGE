import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PlatformUsersComponent } from './platform-users.component';
import { ToastService } from '../../../../../core/services/toast.service';

describe('PlatformUsersComponent (static mock data)', () => {
  let fixture: ComponentFixture<PlatformUsersComponent>;
  let component: PlatformUsersComponent;
  let toast: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [PlatformUsersComponent],
      providers: [provideRouter([])]
    });
    fixture = TestBed.createComponent(PlatformUsersComponent);
    component = fixture.componentInstance;
    toast = TestBed.inject(ToastService);
    fixture.detectChanges();
  });

  function el(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function rowNames(): string[] {
    return Array.from(el().querySelectorAll('.pa-cell-user')).map(cell => {
      const clone = cell.cloneNode(true) as HTMLElement;
      clone.querySelector('.pa-cell-avatar')?.remove();
      return clone.textContent?.trim() ?? '';
    });
  }

  it('renders the mock directory with local pagination', () => {
    expect(component.users().length).toBe(18);
    expect(component.visibleUsers().length).toBe(8);
    expect(component.pageCount()).toBe(3);
    expect(el().querySelector('[data-testid="pa-users-table"]')).not.toBeNull();
  });

  it('filters the table locally by search text', () => {
    component.setSearch('sarah');
    fixture.detectChanges();

    expect(component.filtered().length).toBe(1);
    expect(rowNames()).toEqual(['Sarah Trabelsi']);

    component.setSearch('no-such-user');
    fixture.detectChanges();
    expect(el().querySelector('[data-testid="pa-users-empty"]')).not.toBeNull();
  });

  it('filters the table locally by role and status', () => {
    component.setRoleFilter('Reviewer');
    fixture.detectChanges();
    expect(component.filtered().every(user => user.role === 'Reviewer')).toBe(true);
    expect(component.filtered().length).toBeGreaterThan(0);

    component.setRoleFilter('');
    component.setStatusFilter('inactive');
    fixture.detectChanges();
    expect(component.filtered().every(user => user.status === 'inactive')).toBe(true);
  });

  it('updates a role locally and confirms with a toast', () => {
    const target = component.users()[0];
    component.openRoleEdit(target);
    component.roleDraft.set('Reviewer');
    component.saveRole();
    fixture.detectChanges();

    expect(component.users()[0].role).toBe('Reviewer');
    expect(
      toast
        .toasts()
        .some((t: { message: string }) => t.message === 'Le rôle a été modifié avec succès.')
    ).toBe(true);
    expect(component.modal()).toBeNull();
  });

  it('toggles the active status locally', () => {
    const target = component.users()[0];
    expect(target.status).toBe('active');

    component.toggleStatus(target);
    fixture.detectChanges();
    expect(component.users()[0].status).toBe('inactive');
    expect(
      toast
        .toasts()
        .some((t: { message: string }) => t.message === "L'utilisateur a été désactivé.")
    ).toBe(true);
  });

  it('adds a user to the local table without any backend call', () => {
    component.openAdd();
    component.setAddField('name', 'Test Person');
    component.setAddField('email', 'test@example.com');
    component.addUser();
    fixture.detectChanges();

    expect(component.users().length).toBe(19);
    expect(component.users().some(u => u.name === 'Test Person')).toBe(true);
    expect(
      toast
        .toasts()
        .some((t: { message: string }) => t.message === "L'utilisateur a été ajouté avec succès.")
    ).toBe(true);
  });

  it('opens the profile modal read-only (no edit controls)', () => {
    component.openProfile(component.users()[0]);
    fixture.detectChanges();

    const modal = el().querySelector('[data-testid="pa-user-profile-modal"]');
    expect(modal).not.toBeNull();
    expect(modal?.textContent).toContain('Ahmed Ben Ali');
    expect(modal?.querySelector('select')).toBeNull();
  });
});
