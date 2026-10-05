package com.codesage.repo.client;

import com.codesage.repo.config.DefaultsProperties;
import lombok.Data;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

/**
 * Resolves the K8s quota values (ResourceQuota + LimitRange) for a repo-tenant.
 *
 * WHY defaults: a namespace must always be provisioned even if a remote
 * quota source is down or does not know this repo-tenant yet — every failure
 * path falls back to the ConfigMap-injected {@link DefaultsProperties}.
 *
 * CodeSage has no quota/billing microservice today, so
 * {@code services.quota.url} is empty by default and this client returns
 * defaults without any network call. If a URL is ever configured, the same
 * catch-all fallback applies: unreachable service, error status, or empty
 * body → defaults. Enabling a repo never fails because another
 * microservice is down.
 */
@Component
@Slf4j
public class QuotaClient {

    private final RestTemplate restTemplate;
    private final DefaultsProperties defaults;

    @Value("${services.quota.url:}")
    private String quotaServiceUrl;

    @Value("${internal.security.token}")
    private String internalToken;

    public QuotaClient(RestTemplate restTemplate, DefaultsProperties defaults) {
        this.restTemplate = restTemplate;
        this.defaults = defaults;
    }

    @Cacheable(value = "repoQuota", key = "#repoId")
    public QuotaResponse getQuotaForRepo(Long repoId) {

        if (quotaServiceUrl == null || quotaServiceUrl.isBlank()) {
            // No remote source configured (default in CodeSage) — the
            // ConfigMap defaults ARE the quota.
            return defaults();
        }

        String url = quotaServiceUrl + "/internal/quotas/" + repoId;
        log.info("[QUOTA] Fetching quota for repo={}", repoId);

        try {
            ResponseEntity<QuotaResponse> response = restTemplate.exchange(
                    url,
                    HttpMethod.GET,
                    new HttpEntity<>(buildHeaders()),
                    QuotaResponse.class
            );
            QuotaResponse quota = response.getBody();

            if (quota == null) {
                log.warn("[QUOTA] Empty body for repo={}, using defaults", repoId);
                return defaults();
            }

            log.info("[QUOTA] Fetched for repo={} cpu={} memory={}",
                    repoId, quota.getMaxCpuPerFunction(), quota.getMaxMemoryPerFunction());
            return quota;

        } catch (Exception e) {
            log.warn("[QUOTA] Could not fetch quota for repo={}: {} — using defaults",
                    repoId, e.getMessage());
            return defaults();
        }
    }

    /** Builds QuotaResponse from the ConfigMap-injected defaults. */
    public QuotaResponse defaults() {
        QuotaResponse r = new QuotaResponse();
        r.setMaxCpuPerFunction(defaults.getMaxCpuPerFunction());
        r.setMaxMemoryPerFunction(defaults.getMaxMemoryPerFunction());
        r.setMaxTotalCpu(defaults.getMaxTotalCpu());
        r.setMaxTotalMemory(defaults.getMaxTotalMemory());
        r.setMaxFunctions(defaults.getMaxFunctions());
        r.setMaxPods(defaults.getMaxPods());
        return r;
    }

    private HttpHeaders buildHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Service-Token", internalToken);
        headers.setContentType(MediaType.APPLICATION_JSON);
        return headers;
    }

    // ── DTO ───────────────────────────────────────────────────────────────

    @Data
    public static class QuotaResponse {
        private String  tenantId;
        private String  maxCpuPerFunction;
        private String  maxMemoryPerFunction;
        private String  maxTotalCpu;
        private String  maxTotalMemory;
        private int     maxFunctions;
        private int     maxPods;
        private Long    softInvocationLimitPerMonth;
    }
}
