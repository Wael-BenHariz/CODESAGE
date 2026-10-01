package com.codesage.repo.tenant.entity;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("RepoTenant.generateNamespaceName — one repo = one namespace")
class RepoTenantTest {

    @Test
    @DisplayName("should convert owner/name to DNS-1123 slug")
    void shouldSlugifyFullName() {
        assertThat(RepoTenant.generateNamespaceName("acme/my-app")).isEqualTo("acme-my-app");
        assertThat(RepoTenant.generateNamespaceName("Amir-Ouni/My App")).isEqualTo("amir-ouni-my-app");
        assertThat(RepoTenant.generateNamespaceName("--weird--name--")).isEqualTo("weird-name");
    }

    @Test
    @DisplayName("should truncate long names to fit the 63-char namespace limit")
    void shouldTruncateLongNames() {
        String fullName = "some-very-long-organization-name/" + "a-repository-name-that-is-extremely-long";
        String slug = RepoTenant.generateNamespaceName(fullName);

        assertThat(slug.length()).isLessThanOrEqualTo(50);
        assertThat(slug).matches("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$");
    }
}
