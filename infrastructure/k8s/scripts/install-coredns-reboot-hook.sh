#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
install -D -m 0755 "$ROOT/infrastructure/k8s/scripts/refresh-coredns.sh" \
  /usr/local/sbin/codesage-refresh-coredns
install -D -m 0644 "$ROOT/infrastructure/k8s/systemd/codesage-refresh-coredns.service" \
  /etc/systemd/system/codesage-refresh-coredns.service
systemctl daemon-reload
systemctl enable --now codesage-refresh-coredns.service
