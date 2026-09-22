import { environment } from './environment';

describe('environment', () => {
  it('should expose the API base URL', () => {
    expect(environment.apiUrl).withContext('apiUrl must be set').toBeTruthy();
  });

  it('should expose the localStorage keys used by auth', () => {
    expect(environment.tokenKey).toBeTruthy();
    expect(environment.userKey).toBeTruthy();
    expect(environment.tokenKey).not.toEqual(environment.userKey);
  });
});
