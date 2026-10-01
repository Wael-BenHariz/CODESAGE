package com.codesage.repo.common.exception;

public class ConflictException extends BusinessException {

    public ConflictException(String message) {
        super("RESOURCE_CONFLICT", message);
    }
}
