package com.codesage.repo.common.exception;


import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.Instant;
import java.util.stream.Collectors;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    //  Handle ALL business exceptions here
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ErrorResponse> handleBusiness(
            BusinessException ex,
            HttpServletRequest request) {

        HttpStatus status = switch (ex.getMessage()) {
            case "UNAUTHORIZED" -> HttpStatus.UNAUTHORIZED;
            case "CONFLICT", "RESOURCE_CONFLICT", "REPO_ALREADY_EXISTS",
                 "REPO_STILL_ENABLED" -> HttpStatus.CONFLICT;
            case "NOT_FOUND", "RESOURCE_NOT_FOUND" -> HttpStatus.NOT_FOUND;
            case "AUTH_SERVICE_ERROR" -> HttpStatus.SERVICE_UNAVAILABLE;
            default -> HttpStatus.BAD_REQUEST;
        };

        return buildResponse(ex, status, request);
    }

    //  Validation errors (400)
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidation(
            MethodArgumentNotValidException ex,
            HttpServletRequest request) {

        String errors = ex.getBindingResult()
                .getFieldErrors()
                .stream()
                .map(FieldError::getDefaultMessage)
                .collect(Collectors.joining(", "));

        return ResponseEntity.badRequest().body(
                ErrorResponse.builder()
                        .timestamp(Instant.now())
                        .status(HttpStatus.BAD_REQUEST.value())
                        .error("VALIDATION_ERROR")
                        .message(errors)
                        .path(request.getRequestURI())
                        .build()
        );
    }

    //  Fallback for unexpected errors (500) — always log the stack, a 500
    //  without a trace is undebuggable.
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(
            Exception ex,
            HttpServletRequest request) {

        log.error("Unhandled exception on {} {}", request.getMethod(),
                request.getRequestURI(), ex);

        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(
                        ErrorResponse.builder()
                                .timestamp(Instant.now())
                                .status(500)
                                .error("INTERNAL_SERVER_ERROR")
                                .message("Unexpected error occurred")
                                .path(request.getRequestURI())
                                .build()
                );
    }

    private ResponseEntity<ErrorResponse> buildResponse(
            BusinessException ex,
            HttpStatus status,
            HttpServletRequest request) {

        return ResponseEntity.status(status)
                .body(
                        ErrorResponse.builder()
                                .timestamp(Instant.now())
                                .status(status.value())
                                .error(ex.getMessage())
                                .message(ex.getErrorCode())
                                .path(request.getRequestURI())
                                .build()
                );
    }
}
