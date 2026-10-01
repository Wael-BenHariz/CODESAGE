package com.codesage.repo;

import io.fabric8.kubernetes.client.KubernetesClient;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

@SpringBootTest
class RepoTenantServiceApplicationTests {

    @MockitoBean
    KubernetesClient kubernetesClient;

    @Test
    void contextLoads() {
    }
}
