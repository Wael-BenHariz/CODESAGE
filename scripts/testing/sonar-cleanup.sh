#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
key="${1:-}"
[[ "$key" == codesage-benchmark-* ]] || { echo 'Pass the exact codesage-benchmark-* project key' >&2; exit 2; }
read -r -p "Type the exact project key to delete ($key): " confirmation
[[ "$confirmation" == "$key" ]] || { echo 'Confirmation did not match; nothing deleted.' >&2; exit 1; }
: "${SONARQUBE_URL:?Set SONARQUBE_URL}"
: "${SONARQUBE_TOKEN:?Set SONARQUBE_TOKEN}"
curl --fail --silent --show-error -u "$SONARQUBE_TOKEN:" -X POST \
  "$SONARQUBE_URL/api/projects/delete?project=$key"
