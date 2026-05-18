import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { environment } from '@env/environment';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.getToken();

  console.log('[AuthInterceptor] URL:', req.url, 'Token present:', !!token);

  const publicAuthUrls = ['/auth/github', '/auth/github/callback', '/auth/refresh', '/auth/login', '/auth/logout'];
  const isPublicAuth = publicAuthUrls.some(url => req.url.includes(url));

  if (token && !isPublicAuth) {
    console.log('[AuthInterceptor] Adding Authorization header');
    req = req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`
      }
    });
  } else if (token && isPublicAuth) {
    console.log('[AuthInterceptor] Skipping - public auth URL');
  } else if (!token) {
    console.log('[AuthInterceptor] Skipping - no token');
  }

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      if (error.status === 401) {
        auth.logout();
        router.navigate(['/login']);
      }
      return throwError(() => error);
    })
  );
};