/**
 * Paginated list envelope exactly as every paginated backend route returns
 * it (`*ListResponse` in `backend/app/schemas/*.py`):
 * `{ items, total, page, per_page, pages }`.
 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}
