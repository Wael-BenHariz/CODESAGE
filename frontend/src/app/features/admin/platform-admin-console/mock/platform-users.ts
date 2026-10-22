/**
 * STATIC MOCK DATA — Platform Administration console (PFE prototype).
 *
 * Local demo data only: this module is never fetched from, written to, or
 * synced with any backend. Components copy it into local signals and mutate
 * that copy; a page refresh resets everything (by design).
 */

/** Role vocabulary shown in the demo (labels match the PFE use cases). */
export type MockUserRole = 'Developer' | 'Reviewer' | 'Organization Admin' | 'Platform Admin';

export type MockUserStatus = 'active' | 'inactive';

export interface MockPlatformUser {
  readonly id: number;
  readonly name: string;
  readonly email: string;
  readonly organization: string;
  readonly role: MockUserRole;
  readonly status: MockUserStatus;
  /** Free-form demo text ('Today', "Il y a 2 heures", …). */
  readonly lastActivity: string;
}

export const MOCK_USER_ROLES: readonly MockUserRole[] = [
  'Developer',
  'Reviewer',
  'Organization Admin',
  'Platform Admin'
];

export const MOCK_USER_ORGANIZATIONS: readonly string[] = ['Company A', 'Company B', 'Company C'];

export const MOCK_USER_STATUSES: readonly MockUserStatus[] = ['active', 'inactive'];

/** Enough records for the filters and pagination to be meaningful. */
export const MOCK_PLATFORM_USERS: readonly MockPlatformUser[] = [
  {
    id: 1,
    name: 'Ahmed Ben Ali',
    email: 'ahmed@example.com',
    organization: 'Company A',
    role: 'Developer',
    status: 'active',
    lastActivity: 'Today'
  },
  {
    id: 2,
    name: 'Sarah Trabelsi',
    email: 'sarah@example.com',
    organization: 'Company A',
    role: 'Reviewer',
    status: 'active',
    lastActivity: '2 hours ago'
  },
  {
    id: 3,
    name: 'Mohamed Mansour',
    email: 'mohamed@example.com',
    organization: 'Company B',
    role: 'Organization Admin',
    status: 'active',
    lastActivity: 'Yesterday'
  },
  {
    id: 4,
    name: 'Yassine Ali',
    email: 'yassine@example.com',
    organization: 'Company C',
    role: 'Developer',
    status: 'inactive',
    lastActivity: '8 days ago'
  },
  {
    id: 5,
    name: 'Leila Haddad',
    email: 'leila@example.com',
    organization: 'Company B',
    role: 'Reviewer',
    status: 'active',
    lastActivity: '35 minutes ago'
  },
  {
    id: 6,
    name: 'Karim Bouazizi',
    email: 'karim@example.com',
    organization: 'Company A',
    role: 'Developer',
    status: 'active',
    lastActivity: '4 hours ago'
  },
  {
    id: 7,
    name: 'Nour Cherif',
    email: 'nour@example.com',
    organization: 'Company C',
    role: 'Platform Admin',
    status: 'active',
    lastActivity: 'Today'
  },
  {
    id: 8,
    name: 'Sami Gharbi',
    email: 'sami@example.com',
    organization: 'Company B',
    role: 'Developer',
    status: 'inactive',
    lastActivity: '15 days ago'
  },
  {
    id: 9,
    name: 'Rania Khelifi',
    email: 'rania@example.com',
    organization: 'Company C',
    role: 'Reviewer',
    status: 'active',
    lastActivity: '1 hour ago'
  },
  {
    id: 10,
    name: 'Tarek Zouari',
    email: 'tarek@example.com',
    organization: 'Company A',
    role: 'Organization Admin',
    status: 'active',
    lastActivity: 'Yesterday'
  },
  {
    id: 11,
    name: 'Amira Jlassi',
    email: 'amira@example.com',
    organization: 'Company B',
    role: 'Developer',
    status: 'active',
    lastActivity: '3 hours ago'
  },
  {
    id: 12,
    name: 'Omar Ben Youssef',
    email: 'omar@example.com',
    organization: 'Company C',
    role: 'Developer',
    status: 'active',
    lastActivity: '6 hours ago'
  },
  {
    id: 13,
    name: 'Insaf Mejri',
    email: 'insaf@example.com',
    organization: 'Company A',
    role: 'Reviewer',
    status: 'inactive',
    lastActivity: '21 days ago'
  },
  {
    id: 14,
    name: 'Fares Hammami',
    email: 'fares@example.com',
    organization: 'Company B',
    role: 'Reviewer',
    status: 'active',
    lastActivity: 'Today'
  },
  {
    id: 15,
    name: 'Cyrine Nairoukh',
    email: 'cyrine@example.com',
    organization: 'Company C',
    role: 'Organization Admin',
    status: 'active',
    lastActivity: '5 hours ago'
  },
  {
    id: 16,
    name: 'Walid Sassi',
    email: 'walid@example.com',
    organization: 'Company A',
    role: 'Developer',
    status: 'active',
    lastActivity: 'Yesterday'
  },
  {
    id: 17,
    name: 'Mariem Boujelbene',
    email: 'mariem@example.com',
    organization: 'Company B',
    role: 'Developer',
    status: 'inactive',
    lastActivity: '30 days ago'
  },
  {
    id: 18,
    name: 'Anis Chaabane',
    email: 'anis@example.com',
    organization: 'Company C',
    role: 'Developer',
    status: 'active',
    lastActivity: '45 minutes ago'
  }
];

/** Deep-ish copy so pages can mutate their local slice safely. */
export function cloneMockUsers(): MockPlatformUser[] {
  return MOCK_PLATFORM_USERS.map(user => ({ ...user }));
}
