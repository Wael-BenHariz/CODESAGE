package com.codesage.repo.tenant.service;

import com.codesage.repo.client.QuotaClient;
import com.codesage.repo.common.exception.BusinessException;
import io.fabric8.kubernetes.api.model.LimitRangeBuilder;
import io.fabric8.kubernetes.api.model.Quantity;
import io.fabric8.kubernetes.api.model.ResourceQuotaBuilder;
import io.fabric8.kubernetes.client.KubernetesClient;
import io.fabric8.kubernetes.client.KubernetesClientException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.Map;

/**
 * Applies ResourceQuota + LimitRange to a repo namespace using the quota
 * values resolved by {@link com.codesage.repo.client.QuotaClient} — remote
 * source when configured, ConfigMap defaults otherwise; the client
 * guarantees a non-null response).
 *
 * No DB rows are kept for quota objects: the repo-namespace pair is
 * deleted wholesale on disable, so the K8s objects are the source of truth.
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class QuotaProvisioningService {

    private static final String QUOTA_NAME = "repo-resource-quota";
    private static final String LIMIT_RANGE_NAME = "repo-limits";

    private final KubernetesClient kubernetesClient;

    public void applyQuotas(String namespace, QuotaClient.QuotaResponse quota) {
        applyResourceQuota(namespace, quota);
        applyLimitRange(namespace, quota);
    }

    private void applyResourceQuota(String namespace, QuotaClient.QuotaResponse quota) {
        log.info("[RESOURCE-QUOTA] Applying namespace={} totalCpu={} totalMemory={} maxPods={}",
                namespace, quota.getMaxTotalCpu(), quota.getMaxTotalMemory(), quota.getMaxPods());

        Map<String, Quantity> hard = new HashMap<>();
        hard.put("limits.cpu", new Quantity(quota.getMaxTotalCpu()));
        hard.put("limits.memory", new Quantity(quota.getMaxTotalMemory()));
        hard.put("count/pods", new Quantity(String.valueOf(quota.getMaxPods())));

        io.fabric8.kubernetes.api.model.ResourceQuota rq = new ResourceQuotaBuilder()
                .withNewMetadata()
                    .withName(QUOTA_NAME)
                    .withNamespace(namespace)
                .endMetadata()
                .withNewSpec()
                    .withHard(hard)
                .endSpec()
                .build();

        try {
            kubernetesClient.resourceQuotas().inNamespace(namespace).resource(rq).createOrReplace();
            log.info("[RESOURCE-QUOTA] Applied in namespace={}", namespace);
        } catch (KubernetesClientException e) {
            log.error("[RESOURCE-QUOTA] Failed namespace={} HTTP={} message={}",
                    namespace, e.getCode(), e.getMessage());
            throw new BusinessException("K8S_ERROR",
                    "Failed to apply ResourceQuota: HTTP " + e.getCode());
        }
    }

    private void applyLimitRange(String namespace, QuotaClient.QuotaResponse quota) {
        log.info("[LIMIT-RANGE] Applying namespace={} defaultCpu={} defaultMemory={}",
                namespace, quota.getMaxCpuPerFunction(), quota.getMaxMemoryPerFunction());

        Map<String, Quantity> containerLimit = new HashMap<>();
        containerLimit.put("cpu", new Quantity(quota.getMaxCpuPerFunction()));
        containerLimit.put("memory", new Quantity(quota.getMaxMemoryPerFunction()));

        io.fabric8.kubernetes.api.model.LimitRange lr = new LimitRangeBuilder()
                .withNewMetadata()
                    .withName(LIMIT_RANGE_NAME)
                    .withNamespace(namespace)
                .endMetadata()
                .withNewSpec()
                    .addNewLimit()
                        .withType("Container")
                        .withDefault(containerLimit)
                        .withDefaultRequest(containerLimit)
                        .withMax(containerLimit)
                    .endLimit()
                .endSpec()
                .build();

        try {
            kubernetesClient.limitRanges().inNamespace(namespace).resource(lr).createOrReplace();
            log.info("[LIMIT-RANGE] Applied in namespace={}", namespace);
        } catch (KubernetesClientException e) {
            log.error("[LIMIT-RANGE] Failed namespace={} HTTP={} message={}",
                    namespace, e.getCode(), e.getMessage());
            throw new BusinessException("K8S_ERROR",
                    "Failed to apply LimitRange: HTTP " + e.getCode());
        }
    }
}
