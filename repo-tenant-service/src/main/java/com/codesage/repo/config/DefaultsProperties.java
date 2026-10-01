package com.codesage.repo.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Safe fallback values injected by the k8s ConfigMap (repo-tenant-config).
 *
 * WHY: enabling a repo must never fail because another microservice is
 * unreachable. Every remote value this service could need has a default
 * here, so provisioning always succeeds even when dependencies are down.
 */
@Getter
@Setter
@Component
@ConfigurationProperties(prefix = "defaults")
public class DefaultsProperties {

    /** Default CPU request/limit per function container. */
    private String maxCpuPerFunction = "500m";

    /** Default memory request/limit per function container. */
    private String maxMemoryPerFunction = "512Mi";

    /** Total CPU cap for the repo namespace (ResourceQuota). */
    private String maxTotalCpu = "10";

    /** Total memory cap for the repo namespace (ResourceQuota). */
    private String maxTotalMemory = "20Gi";

    /** Maximum number of functions allowed in the repo namespace. */
    private int maxFunctions = 10;

    /** Maximum number of pods allowed in the repo namespace. */
    private int maxPods = 50;
}
