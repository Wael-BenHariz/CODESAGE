package com.codesage.repo.tenant.entity;

import com.codesage.repo.common.entity.BaseEntity;
import com.codesage.repo.tenant.enums.RepoProvisioningStatus;
import com.codesage.repo.tenant.enums.RepoStatus;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.util.UUID;

/**
 * ONE repo maps to ONE tenant (backed by ONE Kubernetes namespace).
 *
 * The row is created when the CodeSage backend reports the repo as enabled
 * (POST /internal/enable); disabling it provisions the namespace named after
 * {@code namespaceName} and later removes both.
 *
 * Schema ownership: the physical table is created by the backend's Alembic
 * migration 009 (shared `codesage` database) — this service runs with
 * ddl-auto: none and must stay in sync with that migration.
 */
@Entity
@Table(name = "repo_tenants")
@Getter
@Setter
public class RepoTenant extends BaseEntity {

    /** External provider repository ID (GitHub numeric id — matches watched_repos.repo_id). */
    @Column(name = "repo_id", nullable = false, unique = true)
    private Long repoId;

    /** Display name — "owner/name". */
    @Column(name = "full_name", nullable = false, length = 512)
    private String fullName;

    /** users.id of whoever selected the repo (ON DELETE SET NULL). */
    @Column(name = "owner_user_id")
    private UUID ownerUserId;

    /** The tenant identity: unique Kubernetes namespace for this repo. */
    @Column(name = "namespace_name", nullable = false, unique = true, length = 63)
    private String namespaceName;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 16)
    private RepoStatus status;

    @Enumerated(EnumType.STRING)
    @Column(name = "provisioning_status", nullable = false, length = 16)
    private RepoProvisioningStatus provisioningStatus = RepoProvisioningStatus.PENDING;

    /**
     * "owner/name" → "owner-name" (DNS-1123 compliant), same sanitizing
     * rules as a slug generator, truncated to 50 chars so the uniqueness
     * suffix ("-1", "-2", …) still fits the 63-char namespace/label limit.
     */
    public static String generateNamespaceName(String fullName) {
        String slug = fullName
                .toLowerCase()
                .replaceAll("[^a-z0-9]", "-")
                .replaceAll("-+", "-")
                .replaceAll("^-|-$", "");

        if (slug.length() > 50) {
            slug = slug.substring(0, 50).replaceAll("-$", "");
        }
        return slug;
    }
}
