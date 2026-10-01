package com.codesage.repo.tenant.dto;

import lombok.Data;

import java.util.UUID;

@Data
public class RepoResponse {
    private UUID id;
    private Long repoId;
    private String fullName;
    private UUID ownerUserId;
    private String namespaceName;
    private String status;
    private String provisioningStatus;
}
