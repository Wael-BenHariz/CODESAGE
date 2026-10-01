package com.codesage.repo.tenant.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class RepoNamespaceResponse {

    private UUID id;
    private String fullName;
    private String namespace;
}
