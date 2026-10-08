import { Component, HostListener, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { EmptyStateComponent } from '../../../../../shared/components/empty-state/empty-state.component';
import { ToastService } from '../../../../../core/services/toast.service';
import {
  MOCK_USER_ORGANIZATIONS,
  MOCK_USER_ROLES,
  MockPlatformUser,
  MockUserRole,
  cloneMockUsers
} from '../../mock/platform-users';

type ModalKind = 'profile' | 'role' | 'org' | 'add';

interface ModalState {
  readonly kind: ModalKind;
  /** null for the "add" modal (no existing user). */
  readonly userId: number | null;
}

const PAGE_SIZE = 8;

/**
 * Platform Administration → Utilisateurs (static PFE prototype) —
 * `/platform-admin/users`.
 *
 * Fully local: the table starts from `cloneMockUsers()` and search,
 * filters, pagination, role/organisation edits, status toggles and the
 * "add user" form all mutate that in-memory copy only. Toasts give the
 * feedback a real mutation would — no HTTP request is ever made, and a
 * page refresh resets the data (by design).
 */
@Component({
  selector: 'app-platform-users',
  standalone: true,
  imports: [FormsModule, EmptyStateComponent],
  templateUrl: './platform-users.component.html'
})
export class PlatformUsersComponent {
  private readonly toast = inject(ToastService);

  readonly roles = MOCK_USER_ROLES;
  readonly organizations = MOCK_USER_ORGANIZATIONS;
  readonly pageSize = PAGE_SIZE;

  /** Mutable local copy of the mock directory. */
  readonly users = signal<MockPlatformUser[]>(cloneMockUsers());

  readonly search = signal('');
  readonly roleFilter = signal('');
  readonly orgFilter = signal('');
  readonly statusFilter = signal('');
  readonly page = signal(1);

  readonly openMenuId = signal<number | null>(null);
  readonly modal = signal<ModalState | null>(null);

  readonly roleDraft = signal<MockUserRole>('Developer');
  readonly orgDraft = signal('');
  readonly addDraft = signal({
    name: '',
    email: '',
    organization: MOCK_USER_ORGANIZATIONS[0],
    role: 'Developer' as MockUserRole
  });

  // ─── derived list ─────────────────────────────────────────────────────────

  readonly filtered = computed(() => {
    const query = this.search().trim().toLowerCase();
    const role = this.roleFilter();
    const org = this.orgFilter();
    const status = this.statusFilter();

    return this.users().filter(user => {
      const matchesQuery =
        query === '' ||
        [user.name, user.email, user.organization, user.role].some(field =>
          field.toLowerCase().includes(query)
        );
      return (
        matchesQuery &&
        (role === '' || user.role === role) &&
        (org === '' || user.organization === org) &&
        (status === '' || user.status === status)
      );
    });
  });

  /** Page count (at least 1) — clamped together with `page()`. */
  readonly pageCount = computed(() => Math.max(1, Math.ceil(this.filtered().length / PAGE_SIZE)));

  readonly currentPage = computed(() => Math.min(this.page(), this.pageCount()));

  readonly visibleUsers = computed(() => {
    const start = (this.currentPage() - 1) * PAGE_SIZE;
    return this.filtered().slice(start, start + PAGE_SIZE);
  });

  /** The user the open modal acts on (null for the add modal). */
  readonly selectedUser = computed(() => {
    const id = this.modal()?.userId;
    return id == null ? null : this.users().find(user => user.id === id) ?? null;
  });

  readonly addValid = computed(() => {
    const draft = this.addDraft();
    return draft.name.trim() !== '' && draft.email.trim() !== '';
  });

  // ─── filters / pagination ────────────────────────────────────────────────

  setSearch(value: string): void {
    this.search.set(value);
    this.resetPage();
  }

  setRoleFilter(value: string): void {
    this.roleFilter.set(value);
    this.resetPage();
  }

  setOrgFilter(value: string): void {
    this.orgFilter.set(value);
    this.resetPage();
  }

  setStatusFilter(value: string): void {
    this.statusFilter.set(value);
    this.resetPage();
  }

  prevPage(): void {
    if (this.currentPage() > 1) {
      this.page.set(this.currentPage() - 1);
    }
  }

  nextPage(): void {
    if (this.currentPage() < this.pageCount()) {
      this.page.set(this.currentPage() + 1);
    }
  }

  private resetPage(): void {
    this.page.set(1);
  }

  // ─── row actions ─────────────────────────────────────────────────────────

  toggleMenu(userId: number): void {
    this.openMenuId.update(open => (open === userId ? null : userId));
  }

  closeMenu(): void {
    this.openMenuId.set(null);
  }

  /** Clicks outside any row's action cell close its menu. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: Event): void {
    const target = event.target as HTMLElement | null;
    if (target && !target.closest('.pa-row-actions')) {
      this.closeMenu();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.modal()) {
      this.closeModal();
    } else {
      this.closeMenu();
    }
  }

  openProfile(user: MockPlatformUser): void {
    this.modal.set({ kind: 'profile', userId: user.id });
    this.closeMenu();
  }

  openRoleEdit(user: MockPlatformUser): void {
    this.roleDraft.set(user.role);
    this.modal.set({ kind: 'role', userId: user.id });
    this.closeMenu();
  }

  openOrgEdit(user: MockPlatformUser): void {
    this.orgDraft.set(user.organization);
    this.modal.set({ kind: 'org', userId: user.id });
    this.closeMenu();
  }

  openAdd(): void {
    this.addDraft.set({
      name: '',
      email: '',
      organization: this.organizations[0],
      role: 'Developer'
    });
    this.modal.set({ kind: 'add', userId: null });
  }

  /** Field setter for the add-user form (templates cannot use arrows). */
  setAddField(field: 'name' | 'email' | 'organization' | 'role', value: string): void {
    this.addDraft.update(draft => ({ ...draft, [field]: value }));
  }

  closeModal(): void {
    this.modal.set(null);
  }

  /** Close only when the backdrop itself was clicked. */
  onOverlayClick(event: Event): void {
    if (event.target === event.currentTarget) {
      this.closeModal();
    }
  }

  saveRole(): void {
    const state = this.modal();
    if (!state || state.userId == null) {
      return;
    }
    const nextRole = this.roleDraft();
    this.users.update(list =>
      list.map(user => (user.id === state.userId ? { ...user, role: nextRole } : user))
    );
    this.closeModal();
    this.toast.success('Le rôle a été modifié avec succès.');
  }

  saveOrg(): void {
    const state = this.modal();
    if (!state || state.userId == null) {
      return;
    }
    const nextOrg = this.orgDraft();
    this.users.update(list =>
      list.map(user => (user.id === state.userId ? { ...user, organization: nextOrg } : user))
    );
    this.closeModal();
    this.toast.success("L'organisation a été modifiée avec succès.");
  }

  toggleStatus(user: MockPlatformUser): void {
    const nextStatus = user.status === 'active' ? 'inactive' : 'active';
    this.users.update(list =>
      list.map(row => (row.id === user.id ? { ...row, status: nextStatus } : row))
    );
    this.closeMenu();
    this.toast.success(
      nextStatus === 'active' ? "L'utilisateur a été activé." : "L'utilisateur a été désactivé."
    );
  }

  addUser(): void {
    if (!this.addValid()) {
      return;
    }
    const draft = this.addDraft();
    this.users.update(list => [
      ...list,
      {
        id: Math.max(0, ...list.map(user => user.id)) + 1,
        name: draft.name.trim(),
        email: draft.email.trim(),
        organization: draft.organization,
        role: draft.role,
        status: 'active',
        lastActivity: '—'
      }
    ]);
    this.closeModal();
    this.toast.success("L'utilisateur a été ajouté avec succès.");
    // Show the new record even when filters hide the last page.
    this.resetPage();
  }

  // ─── template helpers ────────────────────────────────────────────────────

  statusLabel(status: MockPlatformUser['status']): string {
    return status === 'active' ? 'Actif' : 'Inactif';
  }

  /** Two-letter avatar fallback ("Ahmed Ben Ali" → "AB"). */
  initials(name: string): string {
    return name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(part => part[0])
      .join('');
  }
}
