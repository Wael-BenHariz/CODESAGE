package com.codesage.repo.tenant.enums;

/**
 * Lifecycle of the tenant/namespace backing a repo.
 */
public enum RepoProvisioningStatus {
    PENDING, PROVISIONING, READY, FAILED
}
