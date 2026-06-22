#!/usr/bin/env bash
#
# Cut a release: tag the current commit, push the tag, and publish a GitHub
# Release whose notes are the commits since the previous release. Pushing a `v*`
# tag triggers .github/workflows/release.yml, which runs the checks and then
# builds + pushes the bot + signal-bridge images to GHCR. Deploy on the host
# with `./deploy/update.sh`.
#
# Usage:
#   ./deploy/release.sh            # bump the PATCH of the latest tag (v1.2.0 -> v1.2.1)
#   ./deploy/release.sh 2.3.1      # release exactly v2.3.1   (the `v` is optional)
#   ./deploy/release.sh v2.3.1     # same — always normalized to a `v` prefix
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Newest existing semver tag (vX.Y.Z), or empty if there are none yet.
latest="$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n1)"

if [[ $# -ge 1 ]]; then
	# Explicit version — accept X.Y.Z or vX.Y.Z, normalize to vX.Y.Z.
	ver="${1#v}"
	if [[ ! "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
		echo "error: version must be X.Y.Z or vX.Y.Z (got '$1')" >&2
		exit 1
	fi
	tag="v$ver"
else
	# No arg — bump the patch of the latest tag, starting at v0.0.1.
	if [[ -z "$latest" ]]; then
		tag="v0.0.1"
	else
		IFS=. read -r major minor patch <<<"${latest#v}"
		tag="v${major}.${minor}.$((patch + 1))"
	fi
fi

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
	echo "error: tag $tag already exists" >&2
	exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
	echo "warning: working tree is dirty — tagging commit $(git rev-parse --short HEAD) as-is" >&2
fi

# Release notes: every commit since the previous tag (or the whole history for
# the first release).
if [[ -n "$latest" ]]; then
	range="${latest}..HEAD"
else
	range="HEAD"
fi
notes="$(git log "$range" --no-merges --pretty=format:'- %s (%h)')"
[[ -z "$notes" ]] && notes="- No changes since ${latest:-the beginning}."

echo "==> Releasing $tag (previous: ${latest:-none}) at $(git rev-parse --short HEAD)"
echo "--- release notes ---"
echo "$notes"
echo "---------------------"

git tag -a "$tag" -m "Release $tag"
git push origin "$tag"

# Publish a GitHub Release pointing at the tag we just pushed (the tag push, not
# this, is what triggers the image build — so no double build). Append a compare
# link to the previous release when there is one.
body="$notes"
if [[ -n "$latest" ]]; then
	repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
	[[ -n "$repo" ]] && body+=$'\n\n'"**Full changelog:** https://github.com/${repo}/compare/${latest}...${tag}"
fi

if command -v gh >/dev/null 2>&1; then
	gh release create "$tag" --title "$tag" --notes "$body" --target "$(git rev-parse HEAD)"
	echo "==> Published GitHub Release $tag"
else
	echo "warning: gh CLI not found — skipped GitHub Release (tag still pushed)" >&2
fi

echo "==> Watch the build:  gh run watch \$(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')"
