import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from './api.service';
import { UserService } from './user.service';

describe('UserService (/users group)', () => {
  let api: jasmine.SpyObj<ApiService>;
  let service: UserService;

  /** Wire fixture shaped like backend UserResponse (schemas/user.py). */
  const dto = {
    id: 'u-1',
    keycloak_id: 'kc-1',
    role: 'REVIEWER',
    github_id: 123,
    login: 'octocat',
    email: 'octo@example.com',
    name: 'Octo Cat',
    avatar_url: 'https://example.com/a.png',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z'
  };

  beforeEach(() => {
    api = jasmine.createSpyObj<ApiService>('ApiService', ['get']);
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: api }]
    });
    service = TestBed.inject(UserService);
  });

  it('lists users from GET /users with pagination params', () => {
    api.get.and.returnValue(of({ items: [dto], total: 1, page: 1, per_page: 20, pages: 1 }));

    let list!: { items: unknown[]; perPage: number };
    service.listUsers(2, 50).subscribe(l => (list = l));

    expect(api.get).toHaveBeenCalledWith('/users', { page: 2, per_page: 50 });
    expect(list.items.length).toBe(1);
    // per_page comes back from the envelope as-is (fixture returns 20).
    expect(list.perPage).toBe(20);
  });

  it('maps snake_case user fields to the camelCase model', () => {
    api.get.and.returnValue(of({ items: [dto], total: 1, page: 1, per_page: 20, pages: 1 }));

    let login = '';
    let keycloakId: string | null = '';
    let avatarUrl: string | null = '';
    service.listUsers().subscribe(l => {
      login = l.items[0].login;
      keycloakId = l.items[0].keycloakId;
      avatarUrl = l.items[0].avatarUrl;
    });

    expect(login).toBe('octocat');
    expect(keycloakId).toBe('kc-1');
    expect(avatarUrl).toBe('https://example.com/a.png');
  });

  it('fetches one user from GET /users/{id}', () => {
    api.get.and.returnValue(of(dto));

    service.getUser('u-1').subscribe();

    expect(api.get).toHaveBeenCalledWith('/users/u-1');
  });

  it('never throws on sparse payloads — missing fields become safe defaults', () => {
    api.get.and.returnValue(
      of({ items: [{ id: 'u-2', login: 'ghost' }], total: 1, page: 1, per_page: 20, pages: 1 })
    );

    let role = '';
    let email: string | null = 'unset';
    service.listUsers().subscribe(l => {
      role = l.items[0].role;
      email = l.items[0].email;
    });

    expect(role).toBe('NONE');
    expect(email).toBeNull();
  });
});
