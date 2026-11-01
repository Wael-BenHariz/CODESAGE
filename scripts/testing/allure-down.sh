#!/usr/bin/env bash
set -euo pipefail
if docker inspect codesage-allure >/dev/null 2>&1; then
  owner="$(docker inspect -f '{{ index .Config.Labels "codesage.testing" }}' codesage-allure)"
  [[ "$owner" == true ]] || { echo 'Refusing to remove an unrelated codesage-allure container.' >&2; exit 1; }
  docker rm -f codesage-allure >/dev/null
fi
