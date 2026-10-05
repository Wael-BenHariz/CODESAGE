package com.codesage.repo.tenant.service;

import com.codesage.repo.client.QuotaClient;
import com.codesage.repo.tenant.entity.RepoTenant;
import com.codesage.repo.tenant.enums.RepoProvisioningStatus;
import com.codesage.repo.tenant.repository.RepoTenantRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * Background provisioning for an enabled repo: apply ResourceQuota +
 * LimitRange to the repo namespace (remote values or ConfigMap defaults),
 * then mark READY.
 *
 * Contract: on ANY failure the namespace is rolled back and the row is
 * marked FAILED so the user can retry (enable) or tear down (disable).
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class ProvisioningService {

    private final RepoTenantRepository repoTenantRepository;
    private final NamespaceService namespaceService;
    private final QuotaProvisioningService quotaProvisioningService;
    private final QuotaClient quotaClient;

    @Async("repoProvisioningExecutor")
    public void provisionRepoAsync(UUID repoDbId, String namespace) {
        log.info("[PROVISION] Starting background provisioning for repo db id={} namespace={}",
                repoDbId, namespace);

        RepoTenant repo = repoTenantRepository.findById(repoDbId)
                .orElseThrow(() -> new RuntimeException("Repo not found: " + repoDbId));

        repo.setProvisioningStatus(RepoProvisioningStatus.PROVISIONING);
        repoTenantRepository.save(repo);

        try {
            // Remote call with ConfigMap defaults fallback — never throws.
            QuotaClient.QuotaResponse quota = quotaClient.getQuotaForRepo(repo.getRepoId());

            quotaProvisioningService.applyQuotas(namespace, quota);
            log.info("[PROVISION] Quotas applied for namespace={}", namespace);

            repo.setProvisioningStatus(RepoProvisioningStatus.READY);
            repoTenantRepository.save(repo);
            log.info("[PROVISION] Complete for namespace={}", namespace);

        } catch (Exception ex) {
            log.error("[PROVISION] Failed for namespace={}: {}", namespace, ex.getMessage(), ex);

            try {
                namespaceService.deleteNamespace(namespace);
                log.info("[PROVISION] Namespace cleaned up: {}", namespace);
            } catch (Exception cleanupEx) {
                log.error("[PROVISION] Cleanup failed for namespace={}: {}",
                        namespace, cleanupEx.getMessage());
            }

            repo.setProvisioningStatus(RepoProvisioningStatus.FAILED);
            repoTenantRepository.save(repo);
        }
    }
}
