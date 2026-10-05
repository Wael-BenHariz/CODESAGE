"""
Configuration Module
Handles all application settings using pydantic-settings.
"""

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    # Application
    APP_NAME: str = "CodeSage"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False)
    API_V1_PREFIX: str = "/api/v1"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    # Serve the interactive API docs and the OpenAPI schema
    # (/api/docs, /api/redoc, /api/openapi.json). Off by default so the API
    # surface is not advertised; enable per environment (backend/.env).
    ENABLE_API_DOCS: bool = False

    # Security
    SECRET_KEY: str = Field(
        ..., description="JWT secret key - must be set in production"
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # TTL (seconds) for the single-use OAuth state stored in Redis during login.
    OAUTH_STATE_TTL_SECONDS: int = 600
    # Refresh-token rotation: when True, refresh JWTs carry a "jti" claim that
    # must be present in the per-user Redis allow-list, and each refresh rotates
    # it (stolen-token detection). Set to False to kill the switch: tokens are
    # then re-issued plainly with no jti check.
    AUTH_REFRESH_ROTATION: bool = True

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://codesage:codesage@postgres:5432/codesage",
        description="Async PostgreSQL connection string",
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = Field(
        default="redis://redis:6379/0", description="Redis connection string for BullMQ"
    )

    # Repo-tenant service — one enabled repo = one Kubernetes namespace.
    # Every call from the selection/webhook flow is BEST-EFFORT: saving
    # watched_repos must never depend on this service being up (failures
    # are logged and swallowed). The internal token must match
    # INTERNAL_SERVICE_TOKEN in the repo-tenant-service secret.
    REPO_TENANT_SERVICE_URL: str = (
        "http://repo-tenant-service.codesage.svc.cluster.local:8085"
    )
    REPO_TENANT_INTERNAL_TOKEN: str = "dev-token"
    REPO_TENANT_TIMEOUT_SECONDS: float = 3.0

    # Invitation mail (plan Step 11 / N4): pluggable MailSender.
    # "console" is the v0.3.0 default — logs subject + body (invite link
    # included) and never sends. "smtp" delivers through the SMTP_*
    # settings below; none of them are required until MAIL_BACKEND=smtp.
    MAIL_BACKEND: str = Field(
        default="console",
        description="Invitation mail sender: console (log only) or smtp",
    )
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@codesage.local"
    SMTP_TLS: bool = True

    # GitHub OAuth
    GITHUB_CLIENT_ID: str = Field(..., description="GitHub OAuth App Client ID")
    GITHUB_CLIENT_SECRET: str = Field(..., description="GitHub OAuth App Client Secret")
    GITHUB_CALLBACK_URL: str = "http://localhost:8000/api/v1/auth/github/callback"
    FRONTEND_URL: str = "http://localhost:4200"

    # Keycloak — the identity/token authority. GitHub OAuth is only reachable
    # as a Keycloak social login provider (broker), never directly by the app.
    KEYCLOAK_URL: str = Field(
        default="http://keycloak-service.codesage.svc.cluster.local:8080/auth",
        description=(
            "Keycloak base URL (in-cluster service URL). Must include the "
            "/auth context path — the server runs with --http-relative-path=/auth."
        ),
    )
    KEYCLOAK_REALM: str = "codesage-realm"
    KEYCLOAK_CLIENT_ID: str = "codesage-backend"
    KEYCLOAK_CLIENT_SECRET: str = Field(
        default="", description="Confidential client secret (service-to-service)"
    )
    KEYCLOAK_AUDIENCE: str = "codesage-angular"
    # Externally reachable Keycloak base (what the browser uses). Tokens are
    # minted by browser redirects through the ingress, so the `iss` claim is
    # the public URL, not the in-cluster service URL. Defaults to
    # {FRONTEND_URL}/auth when empty.
    KEYCLOAK_PUBLIC_URL: str = ""
    # Keycloak rarely rotates RS256 signing keys, but JWKS must be refetched
    # when it does — cache TTL (seconds) for the fetched JWKS document.
    KEYCLOAK_JWKS_CACHE_TTL: int = 3600
    # Exact `iss` values accepted for access tokens (env: JSON array, e.g.
    # '["http://10.171.24.201/auth/realms/codesage-realm"]'). Empty/unset
    # falls back to [KEYCLOAK_ISSUER], which keeps pre-existing behavior.
    # Multiple entries exist for IP/host migrations: list the old and new
    # issuer during cutover so live tokens keep validating. Every entry must
    # end with /realms/{KEYCLOAK_REALM} (enforced by validate_allowed_issuers
    # at startup) — a cross-realm issuer can never pass.
    KEYCLOAK_ALLOWED_ISSUERS: list[str] = Field(
        default_factory=list,
        description="JSON array of exact iss values accepted; empty = [KEYCLOAK_ISSUER]",
    )

    @property
    def KEYCLOAK_JWKS_URI(self) -> str:
        # Fetched server-side: use the in-cluster service URL.
        return f"{self.KEYCLOAK_URL}/realms/{self.KEYCLOAK_REALM}/protocol/openid-connect/certs"

    @property
    def KEYCLOAK_ISSUER(self) -> str:
        base = (self.KEYCLOAK_PUBLIC_URL or f"{self.FRONTEND_URL}/auth").rstrip("/")
        return f"{base}/realms/{self.KEYCLOAK_REALM}"

    @property
    def KEYCLOAK_EFFECTIVE_ISSUERS(self) -> list[str]:
        """The allow-list actually enforced at token validation (never empty)."""
        return list(self.KEYCLOAK_ALLOWED_ISSUERS) or [self.KEYCLOAK_ISSUER]

    # GitHub App (for webhook integration)
    GITHUB_APP_ID: str = Field(..., description="GitHub App ID")
    GITHUB_APP_SLUG: str = Field(
        default="", description="GitHub App slug used for installation URL"
    )
    GITHUB_APP_PRIVATE_KEY: str = Field(..., description="GitHub App private key (PEM)")
    GITHUB_WEBHOOK_SECRET: str = Field(..., description="GitHub webhook secret")
    STATE_TOKEN_SECRET: str = Field(
        ..., description="Secret used to sign GitHub App state tokens"
    )

    # Google Gemini AI
    GEMINI_API_KEY: str = Field(
        ..., description="Google Gemini API key (legacy client)"
    )
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_MAX_TOKENS: int = 8192
    GEMINI_TEMPERATURE: float = 0.7

    # SonarQube (static analysis engine)
    # NOTE: the Helm release installs the service as sonarqube-sonarqube
    # (release name + chart name) — the short form does not resolve in-cluster.
    SONARQUBE_URL: str = "http://sonarqube-sonarqube.sonarqube.svc.cluster.local:9000"
    SONARQUBE_TOKEN: str = ""
    SONARQUBE_ANALYSIS_TIMEOUT: int = 120
    SONARQUBE_POLL_INTERVAL: int = 3
    SONARQUBE_PROJECT_PREFIX: str = "codesage-review"

    # Semgrep — standalone scan service (OSS rules, no account/token).
    # The worker uploads a tar.gz of the SAME files SonarQube scans to
    # POST /scan. SEMGREP_ENABLED=false restores the sonar-only behaviour
    # (a failed/disabled Semgrep never fails a review — partial-failure
    # tolerance lives in the worker, Step 5).
    SEMGREP_ENABLED: bool = True
    SEMGREP_SERVICE_URL: str = "http://semgrep-service:8080"
    # Scan budget per /scan call (sent as the request's timeout param).
    # The HTTP wait is budget + 40 s so the SERVICE's own hard kill
    # (budget + 30 s) reports a clean 504 before the client gives up.
    SEMGREP_TIMEOUT_SECONDS: int = 60
    # Client-side pre-flight cap; must mirror the service's upload limit.
    SEMGREP_MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024

    GROQ_API_KEY: str = Field(..., description="Groq API key (active review LLM)")
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    # Per-user LLM API keys are AES-Fernet encrypted at rest with this key.
    # Required: startup fails fast with a clear error if missing/invalid
    # (validate_default so an absent env var still runs the validator).
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    LLM_ENCRYPTION_KEY: str = Field(
        default="",
        validate_default=True,
        description="Fernet key used to encrypt per-user LLM API keys at rest",
    )

    # Groq free tier TPM (~8000 tokens/request) leaves no room for the full
    # 100k-char fetch cap inside one prompt: cap the diff the LLM sees per
    # review so large PRs degrade to a partial review instead of a 413.
    LLM_DIFF_CHAR_CAP: int = 16000
    AGENT_SECURITY_TEMPERATURE: float = 0.2
    AGENT_COMPLEXITY_TEMPERATURE: float = 0.3
    AGENT_PERFORMANCE_TEMPERATURE: float = 0.3
    AGENT_STYLE_TEMPERATURE: float = 0.4
    AGENT_TEST_TEMPERATURE: float = 0.4
    AGENT_ORCHESTRATOR_TEMPERATURE: float = 0.2
    AGENT_ORCHESTRATOR_MAX_TOKENS: int = 8192

    # BullMQ
    BULLMQ_REVIEW_QUEUE: str = "review-requests"
    BULLMQ_CONCURRENCY: int = 5

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:4200",
        "http://localhost:8080",
    ]

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return v

    @field_validator("MAIL_BACKEND")
    @classmethod
    def validate_mail_backend(cls, v: str) -> str:
        """Fail startup fast on an unknown sender instead of at first invite."""
        allowed = {"console", "smtp"}
        if v not in allowed:
            raise ValueError(
                f"MAIL_BACKEND must be one of {sorted(allowed)}, got {v!r}"
            )
        return v

    @field_validator("GITHUB_APP_PRIVATE_KEY")
    @classmethod
    def validate_private_key(cls, v: str) -> str:
        # Remove common PEM formatting issues
        v = v.replace("\\n", "\n").strip()
        if not v.startswith("-----BEGIN"):
            raise ValueError("GITHUB_APP_PRIVATE_KEY must be a valid PEM key")
        return v

    @field_validator("LLM_ENCRYPTION_KEY")
    @classmethod
    def validate_llm_encryption_key(cls, v: str) -> str:
        """Fail startup fast when the per-user key encryption key is unusable.

        Constraint: a missing LLM_ENCRYPTION_KEY must abort boot with an
        actionable message instead of surfacing later as encrypt/decrypt
        failures on the settings endpoints.
        """
        if not v:
            raise ValueError(
                "LLM_ENCRYPTION_KEY is required but missing. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())" and add it to backend/.env'
            )
        from cryptography.fernet import Fernet  # deferred: keep import light

        try:
            Fernet(v.encode())
        except Exception as exc:
            raise ValueError(
                "LLM_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())" and replace the value in '
                "backend/.env"
            ) from exc
        return v

    @model_validator(mode="after")
    def validate_allowed_issuers(self) -> "Settings":
        """Reject an issuer allow-list entry that does not target KEYCLOAK_REALM.

        Guards requirement: every accepted ``iss`` must be an issuer OF THIS
        REALM (end with ``/realms/{KEYCLOAK_REALM}``) — otherwise a token from
        a different realm on the same Keycloak could be allow-listed by
        mistake. Runs on the effective list (empty setting falls back to
        [KEYCLOAK_ISSUER], which conforms by construction).
        """
        suffix = f"/realms/{self.KEYCLOAK_REALM}"
        for issuer in self.KEYCLOAK_EFFECTIVE_ISSUERS:
            if not issuer.endswith(suffix):
                raise ValueError(
                    f"KEYCLOAK_ALLOWED_ISSUERS entry {issuer!r} is invalid: every "
                    f"allowed issuer must end with {suffix!r} (the issuer of realm "
                    f"{self.KEYCLOAK_REALM!r})"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Convenience accessor
settings = get_settings()
