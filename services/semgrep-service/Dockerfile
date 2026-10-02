# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Stage 1 — bake the OSS rule packs from the public Semgrep registry.
# No account, no token: https://semgrep.dev/c/<pack> serves plain YAML.
# sha256 pins keep the build reproducible — if upstream pack content
# changes, the build FAILS LOUDLY instead of silently scanning different
# rules. Refresh deliberately: download, sha256sum, bump the ARGs
# (procedure in README.md).
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS rules

ARG P_DEFAULT_SHA256=3f7d40a75e96d29602385193fba95faaa87163b26f75d44e19b01154c0a5a75d
ARG P_SECURITY_AUDIT_SHA256=b109a039df712f30c6d3e25e1e8358053fd0f1c91b92d0e8d2871cd141fe602f
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && mkdir -p /opt/semgrep-rules \
    && curl -fsSL --retry 3 https://semgrep.dev/c/p/default \
        -o /opt/semgrep-rules/p-default.yaml \
    && echo "${P_DEFAULT_SHA256}  /opt/semgrep-rules/p-default.yaml" \
        | sha256sum -c - \
    && curl -fsSL --retry 3 https://semgrep.dev/c/p/security-audit \
        -o /opt/semgrep-rules/p-security-audit.yaml \
    && echo "${P_SECURITY_AUDIT_SHA256}  /opt/semgrep-rules/p-security-audit.yaml" \
        | sha256sum -c - \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Stage 2 — runtime: pinned semgrep CLI, non-root user, no network at runtime
# (rules are local; scans run with --metrics=off --disable-version-check).
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ARG SEMGREP_VERSION=1.178.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/semgrep

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    "semgrep==${SEMGREP_VERSION}" \
    && rm -f /tmp/requirements.txt

# Non-root user with a writable HOME (semgrep caches live under ~/.semgrep);
# /tmp is 1777 by default and holds the per-request temp dirs.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin semgrep \
    && mkdir -p /app \
    && chown semgrep:semgrep /app

COPY --from=rules --chown=semgrep:semgrep /opt/semgrep-rules /opt/semgrep-rules
COPY --chown=semgrep:semgrep app /app/app

WORKDIR /app
USER 10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
