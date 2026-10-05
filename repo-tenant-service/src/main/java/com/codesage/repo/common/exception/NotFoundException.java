package com.codesage.repo.common.exception;

public class NotFoundException extends BusinessException {

    public NotFoundException(String message) {
        super("RESOURCE_NOT_FOUND", message);
    }
}
