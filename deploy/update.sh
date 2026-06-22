#!/usr/bin/env bash
#
# Pull the latest released images from GHCR and (re)start the stack on the host.
# Run this on the deploy host (the Mac Mini) from the cloned repo. No building
# happens here — images are built+published by .github/workflows/release.yml.
#
# Usage:
#   ./deploy/update.sh                          # pull :latest and restart
#   SIGNALBOT_IMAGE_TAG=v1.2.3 ./deploy/update.sh   # pin a specific release
#   SIGNALBOT_BUILD=1 ./deploy/update.sh        # fallback: build locally instead of pulling
#
# Data volumes (./data, ./signal-cli-config) persist across updates — only the
# images are swapped.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f .env ]]; then
	echo "error: .env not found in $(pwd) — copy .env.example and fill it in first." >&2
	exit 1
fi

compose() { docker compose -p signal-bot -f docker-compose.prod.yml "$@"; }

if [[ "${SIGNALBOT_BUILD:-0}" == "1" ]]; then
	echo "==> Building images locally and starting…"
	compose up -d --build --remove-orphans
else
	echo "==> Pulling images (${SIGNALBOT_IMAGE_TAG:-latest})…"
	compose pull
	echo "==> Starting…"
	compose up -d --remove-orphans
fi

echo "==> Running containers:"
compose ps
echo
echo "Logs:  docker compose -p signal-bot -f docker-compose.prod.yml logs -f bot"
