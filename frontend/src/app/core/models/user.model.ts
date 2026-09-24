export interface User {
  id: string;
  login: string;
  email: string;
  name: string | null;
  avatarUrl: string;
  createdAt: string;
  updatedAt: string;
}

export interface AuthResponse {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  user: User;
}

export interface TokenPayload {
  sub: string;
  login: string;
  exp: number;
  iat: number;
}
