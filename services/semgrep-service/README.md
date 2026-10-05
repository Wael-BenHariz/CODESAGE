# Semgrep Scan Service

Standalone, always-on HTTP service that scans uploaded source trees with
**Semgrep OSS**. No Semgrep account, no token, no `semgrep login` — rules
are baked into the image at build time and every scan runs with
`--metrics=off --disable-version-check`.

Part of the CodeSage review pipeline (plan: `docs/SEMGREP_INTEGRATION_PLAN.md`).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness — process is up |
| `GET` | `/readyz` | Readiness — semgrep binary found **and** rules baked in (else 503) |
| `POST` | `/scan` | Multipart `tar.gz` upload; returns the semgrep JSON report as-is |

`POST /scan` query parameters:

| Param | Default | Meaning |
|---|---|---|
| `languages` | *(none)* | Comma-separated filter (`python,java,...`); expands to `--include` globs. Unknown names → 422 |
| `timeout` | `SEMGREP_TIMEOUT_SECONDS` (60) | Semgrep `--timeout`; clamped to `MAX_SCAN_TIMEOUT_SECONDS` (600) |

Status codes: `400` invalid/unsafe archive · `413` size caps ·
`422` no files / bad params · `502` semgrep failure · `504` hard timeout.

## How it runs semgrep

```
semgrep scan --json --metrics=off --disable-version-check \
  --timeout <n> --config /opt/semgrep-rules [--include <glob>...] <dir>
```

- Launched with `asyncio.create_subprocess_exec` (never a shell string).
- Exit codes: `0` = clean, `1` = findings (parsed, **not** an error),
  `>= 2` = failure → HTTP 502. Exit `1` with non-JSON stdout is a failure.
- `--timeout <n>` is semgrep's **per-rule-per-file** limit (semgrep
  semantics, default 5 s); the **overall** budget is the hard kill at
  `timeout + KILL_GRACE_SECONDS` (default 30 s) → 504.
- Rule-pack load takes ≈40 s cold (1087 rules from p/default +
  p/security-audit) — a default 60 s request fits, but leave headroom
  for big inputs.
- Concurrency: `MAX_CONCURRENT_SCANS` semaphore (default 2).

## Security guards (`app/extractor.py`)

Each upload gets a fresh temp dir (removed in `finally`-style cleanup via
`TemporaryDirectory`). Extraction rejects: `..`/absolute paths, symlink and
hardlink members, device/FIFO members, archives over
`MAX_EXTRACTED_BYTES` (64 MiB) or `MAX_EXTRACTED_FILES` (5000), and the
upload itself is capped at `MAX_UPLOAD_BYTES` (5 MiB).

## Environment variables

| Env | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENT_SCANS` | `2` | Concurrent scan processes |
| `MAX_UPLOAD_BYTES` | `5242880` | Upload cap (413) |
| `MAX_EXTRACTED_BYTES` | `67108864` | Extracted-size cap (413) |
| `MAX_EXTRACTED_FILES` | `5000` | File-count cap (413) |
| `SEMGREP_BINARY` | `semgrep` | CLI to execute |
| `SEMGREP_RULES_DIR` | `/opt/semgrep-rules` | Baked rules directory |
| `SEMGREP_TIMEOUT_SECONDS` | `60` | Default scan timeout |
| `MAX_SCAN_TIMEOUT_SECONDS` | `600` | Timeout ceiling |
| `KILL_GRACE_SECONDS` | `30` | Extra time before hard kill |

## Local development

```bash
cd services/semgrep-service
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -v          # unit tests; smoke auto-skips without semgrep
```

### Real-semgrep smoke test

```bash
pip install semgrep==1.178.0
# rules: the same registry packs the Dockerfile bakes (public, no account)
mkdir -p /tmp/semgrep-rules
curl -fsSL https://semgrep.dev/c/p/default -o /tmp/semgrep-rules/p-default.yaml
curl -fsSL https://semgrep.dev/c/p/security-audit -o /tmp/semgrep-rules/p-security-audit.yaml
SEMGREP_RULES_DIR=/tmp/semgrep-rules \
  python -m pytest tests/test_smoke_semgrep.py -v
```

The fixture (`tests/fixtures/vulnerable/app.py`) contains `eval(input())`,
a hardcoded password, and `pickle.loads()`; the smoke asserts the packs
flag **eval** and **pickle** (these packs only carry framework-specific
password rules, so the password line is intentionally not asserted).

## Docker build (reproducible)

```bash
docker build -t semgrep-service:local services/semgrep-service
docker run --rm -p 8080:8080 semgrep-service:local
curl -s localhost:8080/readyz
```

Three pins make the build reproducible:

- `--build-arg SEMGREP_VERSION=1.178.0` — exact semgrep CLI from PyPI.
- `--build-arg P_DEFAULT_SHA256=<hash>` — sha256 of the `p/default` pack
  fetched from `https://semgrep.dev/c/p/default`.
- `--build-arg P_SECURITY_AUDIT_SHA256=<hash>` — sha256 of the
  `p/security-audit` pack.

If upstream updates a pack, the build **fails at `sha256sum -c`** instead
of silently scanning different rules.

### Updating the baked rules

```bash
# 1. fetch the current packs and hash them
curl -fsSL https://semgrep.dev/c/p/default -o /tmp/p-default.yaml
curl -fsSL https://semgrep.dev/c/p/security-audit -o /tmp/p-security-audit.yaml
sha256sum /tmp/p-default.yaml /tmp/p-security-audit.yaml

# 2. bump the matching ARG defaults in the Dockerfile (or pass
#    --build-arg) and rebuild
docker build \
  --build-arg P_DEFAULT_SHA256=<new-hash> \
  --build-arg P_SECURITY_AUDIT_SHA256=<new-hash> \
  -t semgrep-service:local services/semgrep-service
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/readyz` 503 "rules dir missing" | Image built without stage-1 rules | Rebuild image; check the pack `sha256sum -c` step and `SEMGREP_RULES_DIR` |
| `/scan` 502 "failed to launch" | `SEMGREP_BINARY` not on PATH | Check env / image contents (`docker run --rm -it <img> which semgrep`) |
| `/scan` 504 | Rule set too large for the timeout | Raise `timeout` param or `SEMGREP_TIMEOUT_SECONDS` |
| `/scan` 413 | Upload/extract caps | Lower input size or raise the `MAX_*` env vars |
| OOMKilled | Rules + scan over memory limit | Raise the container memory limit in the k8s manifest |
