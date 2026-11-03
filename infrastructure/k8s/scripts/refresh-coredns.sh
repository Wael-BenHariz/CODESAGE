#!/usr/bin/env bash
set -euo pipefail

KUBECTL="${KUBECTL:-/usr/local/bin/kubectl}"
KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
export KUBECONFIG

# CoreDNS reads the node resolver through /etc/resolv.conf. After a host
# reboot that file may have changed while the existing pod still has its old
# snapshot, so wait for the API and recreate CoreDNS to pick up the new one.
for attempt in $(seq 1 60); do
  if "$KUBECTL" -n kube-system get deployment coredns >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    echo "CoreDNS deployment was not available after waiting for k3s" >&2
    exit 1
  fi
  sleep 5
done

"$KUBECTL" -n kube-system rollout restart deployment/coredns
"$KUBECTL" -n kube-system rollout status deployment/coredns --timeout=180s
