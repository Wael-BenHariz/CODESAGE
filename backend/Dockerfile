# CodeSage Backend Dockerfile (multi-stage, Alpine + sonar-scanner)

### Stage 1: builder
FROM python:3.11-alpine AS builder

RUN apk add --no-cache \
    gcc musl-dev libffi-dev postgresql-dev \
    openjdk17-jre-headless curl unzip bash

WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

ENV SONAR_SCANNER_VERSION=5.0.1.3006
RUN curl -sSLo /tmp/sonar.zip \
      https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip \
    && unzip /tmp/sonar.zip -d /opt/ \
    && rm /tmp/sonar.zip

### Stage 2: final
FROM python:3.11-alpine AS final

# ENV does not carry across stages — redeclare for the COPY below.
ENV SONAR_SCANNER_VERSION=5.0.1.3006

# libpq: asyncpg/psql runtime bits; JRE: sonar-scanner runs inside the
# worker; bash + curl: entrypoint scripts and the compose healthcheck.
RUN apk add --no-cache libpq openjdk17-jre-headless bash curl

# Upgrade Alpine packages to receive security fixes.
RUN apk upgrade --no-cache

# The python:3.11 base bundles setuptools 79, whose _vendor/ tree ships old
# wheel/jaraco copies that the Trivy gate flags (CVE-2026-24049/23949).
# requirements.txt floors setuptools>=84.2.1 (clean _vendor); drop the base
# copy so the COPY below doesn't merge two versions' dist-info metadata.
RUN pip uninstall -y setuptools

COPY --from=builder /install /usr/local
COPY --from=builder /opt/sonar-scanner-${SONAR_SCANNER_VERSION}-linux /opt/sonar-scanner
# The bundled JRE is a glibc build and cannot exec on musl (Alpine) — drop it
# and disable the embedded-JRE flag so the launcher uses system OpenJDK 17.
RUN rm -rf /opt/sonar-scanner/jre \
    && sed -i 's/use_embedded_jre=true/use_embedded_jre=false/' /opt/sonar-scanner/bin/sonar-scanner
ENV PATH="/opt/sonar-scanner/bin:${PATH}"

WORKDIR /app
COPY . .

RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
