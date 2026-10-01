package com.codesage.repo.security;

import com.codesage.repo.config.InternalSecurityProperties;
import jakarta.annotation.Nonnull;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Validates the X-Service-Token header on internal (service-to-service)
 * endpoints called by the CodeSage backend.
 */
@Component
@RequiredArgsConstructor
public class InternalServiceFilter extends OncePerRequestFilter {

    private final InternalSecurityProperties securityProperties;

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            @Nonnull HttpServletResponse response,
            @Nonnull FilterChain filterChain
    ) throws ServletException, IOException {

        String path = request.getRequestURI();

        boolean internalEndpoint = path.startsWith("/api/v1/repos/internal/");

        if (internalEndpoint) {

            String token = request.getHeader("X-Service-Token");

            if (token == null || !token.equals(securityProperties.getToken())) {

                response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                response.getWriter().write("Invalid internal token");
                return;
            }
        }

        filterChain.doFilter(request, response);
    }
}
