package com.codesage.repo.tenant.service;

import com.codesage.repo.tenant.dto.RepoEnableRequest;
import com.codesage.repo.tenant.dto.RepoNamespaceResponse;
import com.codesage.repo.tenant.dto.RepoResponse;
import com.codesage.repo.tenant.entity.RepoTenant;
import com.codesage.repo.tenant.enums.RepoProvisioningStatus;
import com.codesage.repo.tenant.enums.RepoStatus;
import com.codesage.repo.tenant.repository.RepoTenantRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@DisplayName("RepoService")
class RepoServiceTest {

    @Mock
    private RepoTenantRepository repoTenantRepository;

    @Mock
    private NamespaceService namespaceService;

    @Mock
    private ProvisioningService provisioningService;

    @InjectMocks
    private RepoService repoService;

    private static final Long REPO_ID = 12345L;

    private RepoEnableRequest sampleRequest() {
        RepoEnableRequest r = new RepoEnableRequest();
        r.setRepoId(REPO_ID);
        r.setFullName("acme/my-app");
        r.setOwnerUserId(UUID.randomUUID());
        return r;
    }

    private RepoTenant sampleRepo() {
        RepoTenant repo = new RepoTenant();
        repo.setId(UUID.randomUUID());
        repo.setRepoId(REPO_ID);
        repo.setFullName("acme/my-app");
        repo.setNamespaceName("acme-my-app");
        repo.setStatus(RepoStatus.DISABLED);
        repo.setProvisioningStatus(RepoProvisioningStatus.PENDING);
        return repo;
    }

    private void stubSaveWithId() {
        when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> {
            RepoTenant r = inv.getArgument(0);
            if (r.getId() == null) {
                r.setId(UUID.randomUUID());
            }
            return r;
        });
    }

    @Nested
    @DisplayName("enableByRepoId()")
    class Enable {

        @Test
        @DisplayName("first enable: creates row + namespace and starts async provisioning")
        void shouldCreateAndEnable() {
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.empty());
            when(repoTenantRepository.existsByNamespaceName("acme-my-app")).thenReturn(false);
            when(namespaceService.namespaceExistsInK8s("acme-my-app")).thenReturn(false);
            stubSaveWithId();

            RepoResponse response = repoService.enableByRepoId(sampleRequest());

            assertThat(response.getRepoId()).isEqualTo(REPO_ID);
            assertThat(response.getFullName()).isEqualTo("acme/my-app");
            assertThat(response.getNamespaceName()).isEqualTo("acme-my-app");
            assertThat(response.getStatus()).isEqualTo("ENABLED");
            assertThat(response.getProvisioningStatus()).isEqualTo("PROVISIONING");
            assertThat(response.getOwnerUserId()).isNotNull();
            verify(namespaceService).createNamespace(any(RepoTenant.class), eq("acme-my-app"));
            verify(provisioningService).provisionRepoAsync(any(UUID.class), eq("acme-my-app"));
        }

        @Test
        @DisplayName("should generate unique namespace when base is taken")
        void shouldGenerateUniqueNamespace() {
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.empty());
            when(repoTenantRepository.existsByNamespaceName("acme-my-app")).thenReturn(true);
            when(repoTenantRepository.existsByNamespaceName("acme-my-app-1")).thenReturn(false);
            when(namespaceService.namespaceExistsInK8s("acme-my-app-1")).thenReturn(false);
            stubSaveWithId();

            RepoResponse response = repoService.enableByRepoId(sampleRequest());

            assertThat(response.getNamespaceName()).isEqualTo("acme-my-app-1");
        }

        @Test
        @DisplayName("should be idempotent when already ENABLED and READY (backend re-fire)")
        void shouldBeIdempotent() {
            RepoTenant repo = sampleRepo();
            repo.setStatus(RepoStatus.ENABLED);
            repo.setProvisioningStatus(RepoProvisioningStatus.READY);
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.of(repo));
            when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> inv.getArgument(0));

            RepoResponse response = repoService.enableByRepoId(sampleRequest());

            assertThat(response.getStatus()).isEqualTo("ENABLED");
            verify(namespaceService, never()).createNamespace(any(), any());
            verify(provisioningService, never()).provisionRepoAsync(any(), any());
        }

        @Test
        @DisplayName("should be idempotent while provisioning is still in flight")
        void shouldBeIdempotentWhileProvisioning() {
            RepoTenant repo = sampleRepo();
            repo.setStatus(RepoStatus.ENABLED);
            repo.setProvisioningStatus(RepoProvisioningStatus.PROVISIONING);
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.of(repo));
            when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> inv.getArgument(0));

            RepoResponse response = repoService.enableByRepoId(sampleRequest());

            assertThat(response.getProvisioningStatus()).isEqualTo("PROVISIONING");
            verify(provisioningService, never()).provisionRepoAsync(any(), any());
        }

        @Test
        @DisplayName("should retry provisioning after a FAILED run")
        void shouldRetryFailed() {
            RepoTenant repo = sampleRepo();
            repo.setStatus(RepoStatus.ENABLED);
            repo.setProvisioningStatus(RepoProvisioningStatus.FAILED);
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.of(repo));
            when(repoTenantRepository.save(any(RepoTenant.class))).thenAnswer(inv -> inv.getArgument(0));
            when(namespaceService.namespaceExistsInK8s("acme-my-app")).thenReturn(true);

            RepoResponse response = repoService.enableByRepoId(sampleRequest());

            assertThat(response.getProvisioningStatus()).isEqualTo("PROVISIONING");
            verify(provisioningService).provisionRepoAsync(repo.getId(), "acme-my-app");
        }
    }

    @Nested
    @DisplayName("disableByRepoId()")
    class Disable {

        @Test
        @DisplayName("should delete namespace AND tenant row (full teardown)")
        void shouldTearDown() {
            RepoTenant repo = sampleRepo();
            repo.setStatus(RepoStatus.ENABLED);
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.of(repo));

            Map<String, Object> result = repoService.disableByRepoId(REPO_ID);

            verify(namespaceService).deleteNamespace("acme-my-app");
            verify(repoTenantRepository).delete(repo);
            assertThat(result.get("status")).isEqualTo("DISABLED");
            assertThat(result.get("namespace")).isEqualTo("acme-my-app");
        }

        @Test
        @DisplayName("should keep tenant row when namespace deletion fails (no orphaned ns)")
        void shouldKeepRowOnK8sFailure() {
            RepoTenant repo = sampleRepo();
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.of(repo));
            doThrow(new RuntimeException("K8S down"))
                    .when(namespaceService).deleteNamespace("acme-my-app");

            assertThatThrownBy(() -> repoService.disableByRepoId(REPO_ID))
                    .isInstanceOf(RuntimeException.class);

            verify(repoTenantRepository, never()).delete(any(RepoTenant.class));
        }

        @Test
        @DisplayName("should be an idempotent no-op for a repo that was never enabled")
        void shouldNoOpWhenAbsent() {
            when(repoTenantRepository.findByRepoId(REPO_ID)).thenReturn(Optional.empty());

            Map<String, Object> result = repoService.disableByRepoId(REPO_ID);

            assertThat(result.get("status")).isEqualTo("ABSENT");
            verify(namespaceService, never()).deleteNamespace(any());
            verify(repoTenantRepository, never()).delete(any(RepoTenant.class));
        }
    }

    @Nested
    @DisplayName("getAllRepoNamespaces()")
    class InternalListing {

        @Test
        @DisplayName("should list only ENABLED repos with their namespaces")
        void shouldListEnabled() {
            RepoTenant enabled = sampleRepo();
            enabled.setStatus(RepoStatus.ENABLED);
            when(repoTenantRepository.findByStatus(RepoStatus.ENABLED)).thenReturn(List.of(enabled));

            List<RepoNamespaceResponse> result = repoService.getAllRepoNamespaces();

            assertThat(result).hasSize(1);
            assertThat(result.get(0).getFullName()).isEqualTo("acme/my-app");
            assertThat(result.get(0).getNamespace()).isEqualTo("acme-my-app");
        }
    }
}
