package com.codesage.repo.tenant.controller;

import com.codesage.repo.tenant.dto.RepoDisableRequest;
import com.codesage.repo.tenant.dto.RepoEnableRequest;
import com.codesage.repo.tenant.dto.RepoNamespaceResponse;
import com.codesage.repo.tenant.dto.RepoResponse;
import com.codesage.repo.tenant.dto.RepoStatusResponse;
import com.codesage.repo.tenant.service.RepoService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * REST API for one repo = one tenant = one Kubernetes namespace.
 *
 * - /internal/**  — called by the CodeSage backend (watched-repos hook),
 *                   protected by the X-Service-Token header
 *                   (InternalServiceFilter), NOT by a user JWT.
 * - everything else — read-only, Keycloak JWT (for the future frontend).
 */
@RestController
@RequestMapping("/api/v1/repos")
@Slf4j
@RequiredArgsConstructor
public class RepoController {

    private final RepoService repoService;

    // ── Internal (X-Service-Token) ────────────────────────────────────────

    /**
     * Watched repo flipped to enabled → create row + namespace (sync),
     * quota provisioning runs async. 202 while provisioning is in flight.
     */
    @PostMapping("/internal/enable")
    public ResponseEntity<RepoResponse> enableRepo(@Valid @RequestBody RepoEnableRequest request) {
        log.info("[INTERNAL] enable repo={} full_name={}", request.getRepoId(), request.getFullName());
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(repoService.enableByRepoId(request));
    }

    /**
     * Watched repo deselected (or removed from the installation) → full
     * teardown. Idempotent: unknown repo → 200 with status=ABSENT.
     */
    @PostMapping("/internal/disable")
    public ResponseEntity<Map<String, Object>> disableRepo(
            @Valid @RequestBody RepoDisableRequest request) {
        log.info("[INTERNAL] disable repo={}", request.getRepoId());
        return ResponseEntity.ok(repoService.disableByRepoId(request.getRepoId()));
    }

    /** Repo → namespace mapping for other microservices. */
    @GetMapping("/internal/namespaces")
    public ResponseEntity<List<RepoNamespaceResponse>> getAllRepoNamespaces() {
        return ResponseEntity.ok(repoService.getAllRepoNamespaces());
    }

    // ── Read-only (Keycloak JWT) ──────────────────────────────────────────

    @GetMapping
    public ResponseEntity<List<RepoResponse>> listRepos() {
        return ResponseEntity.ok(repoService.listRepos());
    }

    @GetMapping("/{id}")
    public ResponseEntity<RepoResponse> getRepo(@PathVariable UUID id) {
        return ResponseEntity.ok(repoService.getRepo(id));
    }

    @GetMapping("/{id}/status")
    public ResponseEntity<RepoStatusResponse> getStatus(@PathVariable UUID id) {
        return ResponseEntity.ok(repoService.getStatus(id));
    }
}
