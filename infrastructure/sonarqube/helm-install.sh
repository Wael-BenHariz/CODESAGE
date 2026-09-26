#!/usr/bin/env bash
# In-cluster SonarQube (community edition) — already installed on the k3s cluster
# (namespace `sonarqube`, service DNS sonarqube-sonarqube.sonarqube.svc.cluster.local:9000).
#
# monitoringPasscode guards /api/ops/* endpoints only. Any random hex works
# (generate: openssl rand -hex 32); the value in use lives in the helm release
# secret of the running install, not in this file.
set -euo pipefail

helm repo add sonarqube https://SonarSource.github.io/helm-chart-sonarqube
helm repo update
kubectl create namespace sonarqube
helm install sonarqube sonarqube/sonarqube \
  --namespace sonarqube \
  --set community.enabled=true \
  --set monitoringPasscode="<monitoring-passcode>"
