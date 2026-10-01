package com.codesage.repo.tenant.service;

import com.codesage.repo.client.QuotaClient;
import com.codesage.repo.common.exception.BusinessException;
import com.codesage.repo.tenant.entity.RepoTenant;
import com.codesage.repo.tenant.enums.RepoProvisioningStatus;
import com.codesage.repo.tenant.enums.RepoStatus;
import com.codesage.repo.tenant.repository.RepoTenantRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Captor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("ProvisioningService — Quota Provisioning")
class ProvisioningServiceTest {

    @Mock
    private RepoTenantRepository repoTenantRepository;

    @Mock
    private NamespaceService namespaceService;

    @Mock
    private QuotaProvisioningService quotaProvisioningService;

    @Mock
    private QuotaClient quotaClient;

    @InjectMocks
    private ProvisioningService provisioningService;

    @Captor
    private ArgumentCaptor<RepoTenant> repoCaptor;

    private final UUID repoDbId = UUID.randomUUID();
    private final String namespace = "acme-my-app";

    private RepoTenant createSavedRepo() {
        RepoTenant r = new RepoTenant();
        r.setId(repoDbId);
        r.setRepoId(12345L);
        r.setFullName("acme/my-app");
        r.setNamespaceName(namespace);
        r.setStatus(RepoStatus.ENABLED);
        r.setProvisioningStatus(RepoProvisioningStatus.PROVISIONING);
        return r;
    }

    private QuotaClient.QuotaResponse sampleQuota() {
        QuotaClient.QuotaResponse q = new QuotaClient.QuotaResponse();
        q.setMaxCpuPerFunction("500m");
        q.setMaxMemoryPerFunction("512Mi");
        q.setMaxTotalCpu("10");
        q.setMaxTotalMemory("20Gi");
        q.setMaxFunctions(10);
        q.setMaxPods(50);
        return q;
    }

    @Test
    @DisplayName("should apply resolved quota and mark READY")
    void shouldProvisionWithQuota() {
        RepoTenant repo = createSavedRepo();
        when(repoTenantRepository.findById(repoDbId)).thenReturn(Optional.of(repo));
        when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> inv.getArgument(0));
        when(quotaClient.getQuotaForRepo(12345L)).thenReturn(sampleQuota());

        provisioningService.provisionRepoAsync(repoDbId, namespace);

        verify(quotaProvisioningService).applyQuotas(eq(namespace), any(QuotaClient.QuotaResponse.class));
        verify(namespaceService, never()).deleteNamespace(anyString());

        verify(repoTenantRepository, atLeastOnce()).save(repoCaptor.capture());
        assertThat(repoCaptor.getAllValues().get(repoCaptor.getAllValues().size() - 1)
                .getProvisioningStatus()).isEqualTo(RepoProvisioningStatus.READY);
    }

    @Test
    @DisplayName("should mark FAILED and roll back namespace when quota apply fails")
    void shouldFailAndRollBack() {
        RepoTenant repo = createSavedRepo();
        when(repoTenantRepository.findById(repoDbId)).thenReturn(Optional.of(repo));
        when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> inv.getArgument(0));
        when(quotaClient.getQuotaForRepo(12345L)).thenReturn(sampleQuota());
        doThrow(new BusinessException("K8S_ERROR", "quota failed"))
                .when(quotaProvisioningService).applyQuotas(anyString(), any());

        provisioningService.provisionRepoAsync(repoDbId, namespace);

        verify(namespaceService).deleteNamespace(namespace);
        verify(repoTenantRepository, atLeastOnce()).save(repoCaptor.capture());
        assertThat(repoCaptor.getAllValues().get(repoCaptor.getAllValues().size() - 1)
                .getProvisioningStatus()).isEqualTo(RepoProvisioningStatus.FAILED);
    }

    @Test
    @DisplayName("should proceed with ConfigMap defaults")
    void shouldProvisionWithDefaults() {
        RepoTenant repo = createSavedRepo();
        when(repoTenantRepository.findById(repoDbId)).thenReturn(Optional.of(repo));
        when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> inv.getArgument(0));
        // QuotaClient contract: missing remote source → non-null defaults response.
        // Build them from a REAL client (calling the mock inside when() would break stubbing).
        QuotaClient realDefaultsSource = new QuotaClient(null, new com.codesage.repo.config.DefaultsProperties());
        when(quotaClient.getQuotaForRepo(12345L)).thenReturn(realDefaultsSource.defaults());

        provisioningService.provisionRepoAsync(repoDbId, namespace);

        ArgumentCaptor<QuotaClient.QuotaResponse> quotaCaptor =
                ArgumentCaptor.forClass(QuotaClient.QuotaResponse.class);
        verify(quotaProvisioningService).applyQuotas(eq(namespace), quotaCaptor.capture());

        QuotaClient.QuotaResponse applied = quotaCaptor.getValue();
        assertThat(applied.getMaxCpuPerFunction()).isEqualTo("500m");
        assertThat(applied.getMaxMemoryPerFunction()).isEqualTo("512Mi");
        assertThat(applied.getMaxTotalCpu()).isEqualTo("10");
        assertThat(applied.getMaxTotalMemory()).isEqualTo("20Gi");
        assertThat(applied.getMaxFunctions()).isEqualTo(10);

        verify(repoTenantRepository, atLeastOnce()).save(repoCaptor.capture());
        assertThat(repoCaptor.getAllValues().get(repoCaptor.getAllValues().size() - 1)
                .getProvisioningStatus()).isEqualTo(RepoProvisioningStatus.READY);
    }
}
