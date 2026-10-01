package com.codesage.repo.tenant.service;

import com.codesage.repo.common.exception.BusinessException;
import com.codesage.repo.tenant.dto.RepoEnableRequest;
import com.codesage.repo.tenant.dto.RepoNamespaceResponse;
import com.codesage.repo.tenant.dto.RepoResponse;
import com.codesage.repo.tenant.dto.RepoStatusResponse;
import com.codesage.repo.tenant.entity.RepoTenant;
import com.codesage.repo.tenant.enums.RepoProvisioningStatus;
import com.codesage.repo.tenant.enums.RepoStatus;
import com.codesage.repo.tenant.repository.RepoTenantRepository;
import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Core repo → tenant logic.
 *
 * - enable(repoId):  ONE repo → ONE namespace/tenant, created synchronously,
 *                    quota provisioned asynchronously (upsert: the row is
 *                    created on first enable — CodeSage never "registers"
 *                    separately)
 * - disable(repoId): full teardown — namespace deleted AND tenant row removed;
 *                    idempotent (unknown repo = nothing to do)
 *
 * The CodeSage backend calls these through /api/v1/repos/internal/** whenever
 * watched_repos flips; every call must therefore be safe to repeat.
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class RepoService {

    private final RepoTenantRepository repoTenantRepository;
    private final NamespaceService namespaceService;
    private final ProvisioningService provisioningService;

    /**
     * Upsert + enable. Called by the backend hook on a watched-repo enable
     * transition (and safe to call again for an already-enabled repo).
     *
     * Idempotent: ENABLED + PENDING/PROVISIONING/READY returns as-is; a
     * previously FAILED provisioning is retried by enabling again.
     */
    @Transactional
    @CacheEvict(value = "activeRepoNamespaces", key = "'all'")
    public RepoResponse enableByRepoId(RepoEnableRequest request) {

        RepoTenant repo = repoTenantRepository.findByRepoId(request.getRepoId())
                .orElseGet(() -> createRow(request));

        // Keep display/owner data fresh (repo renamed, re-enabled by another
        // session, …).
        repo.setFullName(request.getFullName());
        if (request.getOwnerUserId() != null) {
            repo.setOwnerUserId(request.getOwnerUserId());
        }

        if (repo.getId() != null
                && repo.getStatus() == RepoStatus.ENABLED
                && repo.getProvisioningStatus() != RepoProvisioningStatus.FAILED) {
            log.info("[REPO] {} already enabled ({}) — nothing to do",
                    repo.getFullName(), repo.getProvisioningStatus());
            return toResponse(repoTenantRepository.save(repo));
        }

        repo.setStatus(RepoStatus.ENABLED);
        RepoTenant saved = repoTenantRepository.save(repo);

        String namespace = saved.getNamespaceName();

        if (!namespaceService.namespaceExistsInK8s(namespace)) {
            namespaceService.createNamespace(saved, namespace);
        }
        log.info("[REPO] Namespace {} ensured for repo {}", namespace, saved.getFullName());

        saved.setProvisioningStatus(RepoProvisioningStatus.PROVISIONING);
        repoTenantRepository.save(saved);

        UUID repoDbId = saved.getId();
        String namespaceName = saved.getNamespaceName();
        if (TransactionSynchronizationManager.isActualTransactionActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    provisioningService.provisionRepoAsync(repoDbId, namespaceName);
                }
            });
        } else {
            provisioningService.provisionRepoAsync(repoDbId, namespaceName);
        }

        return toResponse(saved);
    }

    /**
     * Full teardown (user decision): delete the K8s namespace AND the
     * tenant row. The row is only removed if namespace deletion succeeded,
     * so a failing cluster never leaks namespaces.
     *
     * Idempotent: disabling an unknown repo is a no-op (the backend fires
     * disable for repos that were never enabled).
     */
    @Transactional
    @CacheEvict(value = "activeRepoNamespaces", key = "'all'")
    public Map<String, Object> disableByRepoId(Long repoId) {

        return repoTenantRepository.findByRepoId(repoId)
                .map(repo -> {
                    namespaceService.deleteNamespace(repo.getNamespaceName());
                    repoTenantRepository.delete(repo);

                    log.info("[REPO] {} disabled — tenant/namespace {} torn down",
                            repo.getFullName(), repo.getNamespaceName());

                    return Map.<String, Object>of(
                            "repoId", repoId,
                            "status", RepoStatus.DISABLED.name(),
                            "namespace", repo.getNamespaceName()
                    );
                })
                .orElseGet(() -> {
                    log.info("[REPO] disable for unknown repo id={} — nothing to do", repoId);
                    return Map.<String, Object>of(
                            "repoId", repoId,
                            "status", "ABSENT",
                            "message", "no tenant exists for this repo"
                    );
                });
    }

    public RepoResponse getRepo(UUID id) {
        return toResponse(repoTenantRepository.findById(id)
                .orElseThrow(() -> new BusinessException("NOT_FOUND", "Repo not found")));
    }

    public List<RepoResponse> listRepos() {
        return repoTenantRepository.findAll().stream()
                .map(this::toResponse)
                .toList();
    }

    public RepoStatusResponse getStatus(UUID id) {
        RepoTenant repo = repoTenantRepository.findById(id)
                .orElseThrow(() -> new BusinessException("NOT_FOUND", "Repo not found"));
        return new RepoStatusResponse(
                repo.getStatus().name(),
                repo.getProvisioningStatus().name());
    }

    @Cacheable(value = "activeRepoNamespaces", key = "'all'")
    public List<RepoNamespaceResponse> getAllRepoNamespaces() {
        return repoTenantRepository.findByStatus(RepoStatus.ENABLED)
                .stream()
                .map(repo -> new RepoNamespaceResponse(
                        repo.getId(),
                        repo.getFullName(),
                        repo.getNamespaceName()))
                .toList();
    }

    private RepoTenant createRow(RepoEnableRequest request) {
        RepoTenant repo = new RepoTenant();
        repo.setRepoId(request.getRepoId());
        repo.setFullName(request.getFullName());
        repo.setOwnerUserId(request.getOwnerUserId());
        repo.setNamespaceName(generateUniqueNamespaceName(request.getFullName()));
        repo.setStatus(RepoStatus.DISABLED);
        repo.setProvisioningStatus(RepoProvisioningStatus.PENDING);
        log.info("[REPO] New repo {} → namespace {}",
                request.getFullName(), repo.getNamespaceName());
        return repo;
    }

    private String generateUniqueNamespaceName(String fullName) {
        String base = RepoTenant.generateNamespaceName(fullName);
        String namespaceName = base;
        int counter = 1;
        while (repoTenantRepository.existsByNamespaceName(namespaceName)
                || namespaceService.namespaceExistsInK8s(namespaceName)) {
            namespaceName = base + "-" + counter++;
        }
        return namespaceName;
    }

    private RepoResponse toResponse(RepoTenant repo) {
        RepoResponse response = new RepoResponse();
        response.setId(repo.getId());
        response.setRepoId(repo.getRepoId());
        response.setFullName(repo.getFullName());
        response.setOwnerUserId(repo.getOwnerUserId());
        response.setNamespaceName(repo.getNamespaceName());
        response.setStatus(repo.getStatus().name());
        response.setProvisioningStatus(repo.getProvisioningStatus().name());
        return response;
    }
}
