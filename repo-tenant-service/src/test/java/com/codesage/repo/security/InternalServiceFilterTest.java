package com.codesage.repo.security;

import com.codesage.repo.config.InternalSecurityProperties;
import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

@DisplayName("InternalServiceFilter — X-Service-Token")
class InternalServiceFilterTest {

    private InternalServiceFilter filter;
    private FilterChain chain;

    @BeforeEach
    void setUp() {
        InternalSecurityProperties props = new InternalSecurityProperties();
        props.setToken("test-token");
        filter = new InternalServiceFilter(props);
        chain = mock(FilterChain.class);
    }

    @Test
    @DisplayName("should reject internal call without token (401)")
    void shouldRejectMissingToken() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
                "GET", "/api/v1/repos/internal/namespaces");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getContentAsString()).isEqualTo("Invalid internal token");
        verify(chain, never()).doFilter(any(), any());
    }

    @Test
    @DisplayName("should reject internal call with wrong token (401)")
    void shouldRejectWrongToken() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
                "GET", "/api/v1/repos/internal/namespaces");
        request.addHeader("X-Service-Token", "wrong");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        verify(chain, never()).doFilter(any(), any());
    }

    @Test
    @DisplayName("should accept internal call with correct token")
    void shouldAcceptCorrectToken() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
                "GET", "/api/v1/repos/internal/namespaces");
        request.addHeader("X-Service-Token", "test-token");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(200);
        verify(chain).doFilter(request, response);
    }

    @Test
    @DisplayName("should not require token on public endpoints")
    void shouldSkipPublicEndpoints() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(
                "GET", "/api/v1/repos");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(request, response);
    }
}
