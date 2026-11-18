#!/usr/bin/env bash
# Télécharge à l'avance les images Docker du projet (ThingsBoard pèse ~1 Go).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose pull
