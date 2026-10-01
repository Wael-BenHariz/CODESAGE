package com.codesage.repo.tenant.dto;

import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.Setter;

/**
 * Payload the CodeSage backend posts to /api/v1/repos/internal/disable when a
 * watched repo is deselected (or removed from the GitHub App installation).
 */
@Getter
@Setter
public class RepoDisableRequest {

    @NotNull(message = "repoId is required")
    private Long repoId;
}
