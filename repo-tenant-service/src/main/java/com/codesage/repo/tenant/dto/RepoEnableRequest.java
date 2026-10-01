package com.codesage.repo.tenant.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.Setter;

import java.util.UUID;

/**
 * Payload the CodeSage backend posts to /api/v1/repos/internal/enable when a
 * watched repo flips to enabled (JSON keys are camelCase — this service's
 * default naming strategy).
 */
@Getter
@Setter
public class RepoEnableRequest {

    @NotNull(message = "repoId is required")
    private Long repoId;

    @NotBlank(message = "Repository full name (owner/name) is required")
    private String fullName;

    /** users.id of the user who selected the repo (optional). */
    private UUID ownerUserId;
}
