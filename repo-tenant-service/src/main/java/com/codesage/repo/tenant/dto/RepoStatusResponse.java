package com.codesage.repo.tenant.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class RepoStatusResponse {

    private String status;
    private String provisioningStatus;
}
