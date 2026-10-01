package com.codesage.repo.tenant.repository;

import com.codesage.repo.tenant.entity.RepoTenant;
import com.codesage.repo.tenant.enums.RepoStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface RepoTenantRepository extends JpaRepository<RepoTenant, UUID> {

    Boolean existsByRepoId(Long repoId);

    Boolean existsByNamespaceName(String namespaceName);

    Optional<RepoTenant> findByRepoId(Long repoId);

    List<RepoTenant> findByStatus(RepoStatus status);
}
