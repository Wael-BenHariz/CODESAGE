package com.codesage.repo.common.exception;

import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@DisplayName("GlobalExceptionHandler")
class GlobalExceptionHandlerTest {

    private GlobalExceptionHandler handler;
    private HttpServletRequest request;

    @BeforeEach
    void setUp() {
        handler = new GlobalExceptionHandler();
        request = mock(HttpServletRequest.class);
        when(request.getRequestURI()).thenReturn("/api/v1/repos/1");
    }

    @Test
    @DisplayName("REPO_STILL_ENABLED → 409 Conflict")
    void repoStillEnabledIsConflict() {
        BusinessException ex = new BusinessException("REPO_STILL_ENABLED", "Disable first");

        ResponseEntity<ErrorResponse> response = handler.handleBusiness(ex, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(response.getBody().getError()).isEqualTo("REPO_STILL_ENABLED");
    }

    @Test
    @DisplayName("REPO_ALREADY_EXISTS → 409 Conflict")
    void repoAlreadyExistsIsConflict() {
        BusinessException ex = new BusinessException("REPO_ALREADY_EXISTS", "Already selected");

        ResponseEntity<ErrorResponse> response = handler.handleBusiness(ex, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    @DisplayName("NOT_FOUND → 404")
    void notFoundIs404() {
        BusinessException ex = new BusinessException("NOT_FOUND", "Repo not found");

        ResponseEntity<ErrorResponse> response = handler.handleBusiness(ex, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody().getStatus()).isEqualTo(404);
    }

    @Test
    @DisplayName("K8S_ERROR → 400")
    void k8sErrorIs400() {
        BusinessException ex = new BusinessException("K8S_ERROR", "Kubernetes error occurred");

        ResponseEntity<ErrorResponse> response = handler.handleBusiness(ex, request);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }
}
