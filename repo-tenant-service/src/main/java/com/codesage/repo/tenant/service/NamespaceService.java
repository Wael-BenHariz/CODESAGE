package com.codesage.repo.tenant.service;

import com.codesage.repo.common.exception.BusinessException;
import com.codesage.repo.tenant.entity.RepoTenant;
import io.fabric8.kubernetes.api.model.NamespaceBuilder;
import io.fabric8.kubernetes.client.KubernetesClient;
import io.fabric8.kubernetes.client.KubernetesClientException;
import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * Creates and deletes the per-repo Kubernetes namespace (the tenant).
 * Keeps no separate namespace table — the repo_tenants row IS the record.
 */
@Service
@Slf4j
@Transactional
@RequiredArgsConstructor
public class NamespaceService {

    private final KubernetesClient kubernetesClient;

    public boolean namespaceExistsInK8s(String name) {
        try {
            return kubernetesClient.namespaces().withName(name).get() != null;
        } catch (KubernetesClientException e) {
            log.warn("Error checking namespace existence for {}: {}", name, e.getMessage());
            return false;
        }
    }

    public void createNamespace(RepoTenant repo, String name) {
        log.info("Creating namespace {} for repo {}", name, repo.getFullName());

        try {
            io.fabric8.kubernetes.api.model.Namespace ns = new NamespaceBuilder()
                    .withNewMetadata()
                        .withName(name)
                        .addToLabels("app.kubernetes.io/managed-by", "repo-tenant-service")
                        .addToLabels("codesage.io/repo-slug", name)
                        .addToAnnotations("codesage.io/repo-full-name", repo.getFullName())
                        .addToAnnotations("codesage.io/repo-id", String.valueOf(repo.getRepoId()))
                    .endMetadata()
                    .build();

            kubernetesClient.namespaces().resource(ns).create();

            log.info("Namespace {} created successfully", name);

        } catch (KubernetesClientException e) {
            log.error("Kubernetes error: status={}, message={}", e.getCode(), e.getMessage());

            if (e.getCode() == 409) {
                log.error("Namespace already exists: {}", name);
                throw new BusinessException(
                        "NAMESPACE_ALREADY_EXISTS",
                        "Namespace already exists: " + name
                );
            }

            throw new BusinessException(
                    "K8S_ERROR",
                    "Kubernetes error occurred: " + e.getMessage()
            );
        }
    }

    public void deleteNamespace(String name) {
        log.info("Deleting namespace {}", name);

        try {
            kubernetesClient.namespaces().withName(name).delete();
            log.info("Namespace {} deletion requested successfully (or it did not exist)", name);

        } catch (KubernetesClientException e) {
            log.error("Failed to delete namespace {}: status={}, message={}",
                    name, e.getCode(), e.getMessage());

            throw new BusinessException(
                    "K8S_ERROR",
                    "Failed to delete namespace: " + e.getMessage()
            );
        }
    }
}
