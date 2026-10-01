package com.codesage.repo.client;

import com.codesage.repo.config.DefaultsProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@DisplayName("QuotaClient — ConfigMap defaults, optional remote source")
class QuotaClientTest {

    @Mock
    private RestTemplate restTemplate;

    private DefaultsProperties defaults;
    private QuotaClient quotaClient;

    @BeforeEach
    void setUp() {
        defaults = new DefaultsProperties();
        quotaClient = new QuotaClient(restTemplate, defaults);
        ReflectionTestUtils.setField(quotaClient, "internalToken", "test-token");
    }

    private QuotaClient.QuotaResponse remoteQuota() {
        QuotaClient.QuotaResponse q = new QuotaClient.QuotaResponse();
        q.setMaxCpuPerFunction("250m");
        q.setMaxMemoryPerFunction("256Mi");
        q.setMaxTotalCpu("4");
        q.setMaxTotalMemory("8Gi");
        q.setMaxFunctions(5);
        q.setMaxPods(20);
        return q;
    }

    @Nested
    @DisplayName("when no remote quota source is configured (CodeSage default)")
    class NoRemoteSource {

        @Test
        @DisplayName("should return ConfigMap defaults without any network call")
        void shouldShortCircuitToDefaults() {
            ReflectionTestUtils.setField(quotaClient, "quotaServiceUrl", "");

            QuotaClient.QuotaResponse quota = quotaClient.getQuotaForRepo(12345L);

            assertThat(quota.getMaxCpuPerFunction()).isEqualTo("500m");
            assertThat(quota.getMaxMemoryPerFunction()).isEqualTo("512Mi");
            assertThat(quota.getMaxTotalCpu()).isEqualTo("10");
            assertThat(quota.getMaxTotalMemory()).isEqualTo("20Gi");
            assertThat(quota.getMaxFunctions()).isEqualTo(10);
            assertThat(quota.getMaxPods()).isEqualTo(50);
            verify(restTemplate, never()).exchange(
                    anyString(), any(HttpMethod.class), any(), eq(QuotaClient.QuotaResponse.class));
        }

        @Test
        @DisplayName("should honor custom defaults injected via ConfigMap")
        void shouldHonorInjectedDefaults() {
            ReflectionTestUtils.setField(quotaClient, "quotaServiceUrl", "");
            defaults.setMaxCpuPerFunction("250m");
            defaults.setMaxTotalMemory("4Gi");
            defaults.setMaxFunctions(3);

            QuotaClient.QuotaResponse quota = quotaClient.getQuotaForRepo(12345L);

            assertThat(quota.getMaxCpuPerFunction()).isEqualTo("250m");
            assertThat(quota.getMaxTotalMemory()).isEqualTo("4Gi");
            assertThat(quota.getMaxFunctions()).isEqualTo(3);
        }
    }

    @Nested
    @DisplayName("when a remote quota source responds")
    class RemoteUp {

        @BeforeEach
        void configureUrl() {
            ReflectionTestUtils.setField(quotaClient, "quotaServiceUrl", "http://quota:8081");
        }

        @Test
        @DisplayName("should return the remote quota")
        void shouldReturnRemoteQuota() {
            when(restTemplate.exchange(
                    eq("http://quota:8081/internal/quotas/12345"),
                    eq(HttpMethod.GET),
                    any(HttpEntity.class),
                    eq(QuotaClient.QuotaResponse.class)))
                    .thenReturn(ResponseEntity.ok(remoteQuota()));

            QuotaClient.QuotaResponse quota = quotaClient.getQuotaForRepo(12345L);

            assertThat(quota.getMaxCpuPerFunction()).isEqualTo("250m");
            assertThat(quota.getMaxTotalMemory()).isEqualTo("8Gi");
        }

        @Test
        @DisplayName("should fall back to defaults on empty body")
        void shouldDefaultOnEmptyBody() {
            when(restTemplate.exchange(
                    anyString(), eq(HttpMethod.GET), any(HttpEntity.class),
                    eq(QuotaClient.QuotaResponse.class)))
                    .thenReturn(ResponseEntity.ok().build());

            QuotaClient.QuotaResponse quota = quotaClient.getQuotaForRepo(12345L);

            assertThat(quota.getMaxCpuPerFunction()).isEqualTo("500m");
            assertThat(quota.getMaxFunctions()).isEqualTo(10);
        }
    }

    @Nested
    @DisplayName("when the remote quota source is unreachable")
    class RemoteDown {

        @Test
        @DisplayName("should fall back to ConfigMap-injected defaults, never throw")
        void shouldDefaultOnConnectionFailure() {
            ReflectionTestUtils.setField(quotaClient, "quotaServiceUrl", "http://quota:8081");

            when(restTemplate.exchange(
                    anyString(), eq(HttpMethod.GET), any(HttpEntity.class),
                    eq(QuotaClient.QuotaResponse.class)))
                    .thenThrow(new ResourceAccessException("Connection refused"));

            QuotaClient.QuotaResponse quota = quotaClient.getQuotaForRepo(12345L);

            assertThat(quota.getMaxCpuPerFunction()).isEqualTo("500m");
            assertThat(quota.getMaxMemoryPerFunction()).isEqualTo("512Mi");
            assertThat(quota.getMaxTotalCpu()).isEqualTo("10");
            assertThat(quota.getMaxTotalMemory()).isEqualTo("20Gi");
            assertThat(quota.getMaxFunctions()).isEqualTo(10);
            assertThat(quota.getMaxPods()).isEqualTo(50);
            assertThat(quota.getSoftInvocationLimitPerMonth()).isNull();
        }
    }
}
