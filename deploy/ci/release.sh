#!/bin/bash
set -euo pipefail

# Common CI release logic — shared by all provider-specific pipeline wrappers.
#
# Usage: release.sh --since <commit>
#
# Prerequisites (CI secrets / env vars — all required, checked every run):
#   FLY_API_TOKEN                                  flyctl deploy auth
#   GIT_REPO_DEPLOY_KEY_<LEADER_SLUG>              leader project clone at boot
#   GIT_REPO_DEPLOY_KEY_<DEPENDENT_NAME>           per [[dependent_project]]
#   DATASET_REPO_DEPLOY_KEY_<NAME>                 per [[dataset_repo]]
#   Any api_key_env from [[llm]] / [[image]] / [[speech]]
#
# The Fly app name is read automatically from fly.toml in the project root.
#
# Steps:
#   1. release_secrets.py check --json   →  blocking pre-flight (every commit)
#   2. release_secrets.py check-release --since <SHA> --json  →  decide apply/none
#   3. release_secrets.py sync [--fly-app <name>]  →  topology discovery + secret sync
#   4. release_secrets.py apply --to <tag> --json  →  build params
#   5. git clone Lens repo → flyctl deploy --build-arg LENS_VERSION=<tag>
#

SINCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --since)
      SINCE="$2"
      shift
      ;;
    *)
      echo "release.sh: unknown option $1" >&2
      exit 1
      ;;
  esac
  shift
done

if [ -z "$SINCE" ]; then
  echo "release.sh: --since is required" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="python3 "$SCRIPT_DIR/release_secrets.py""

# Detect Fly app name from fly.toml (must exist in project root)
if [ ! -f fly.toml ]; then
  echo "release.sh: fly.toml not found in project root" >&2
  exit 1
fi
# Resolve to an absolute path up front: step 5 passes the cloned Lens repo as
# flyctl's WORKING_DIRECTORY, which flyctl also uses as the base for
# resolving a relative --config path — a bare "fly.toml" would then be
# looked up inside the clone instead of the project root.
FLY_TOML="$(pwd)/fly.toml"
FLY_APP=$(python3 -c "import tomllib; print(tomllib.load(open('fly.toml','rb'))['app'])")

# Step 1 — pre-flight secrets check (every commit, fail fast on drift)
# Most secrets (deploy keys, API keys, Caddy auth) are already on Fly from
# `lens deploy init` — CI only needs FLY_API_TOKEN for `flyctl deploy`.
$PY check --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
missing_env = [s['name'] for s in data.get('secrets', []) if not s['set_in_env']]
required = {'FLY_API_TOKEN'}
missing_required = [n for n in missing_env if n in required]
missing_optional = [n for n in missing_env if n not in required]
if missing_required:
    print('release.sh: FATAL — FLY_API_TOKEN is not set in CI environment')
    sys.exit(1)
if missing_optional:
    print('release.sh: WARNING — the following are not in CI environment:')
    for n in missing_optional:
        print(f'  {n}')
    print('release.sh: these are already on Fly from lens deploy init — skipping')
print('release.sh: CI secrets check passed')
"

# Step 2 — check whether a release was requested
CHECK=$($PY check-release --since "$SINCE" --json)
ACTION=$(echo "$CHECK" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('action','none'))")
TARGET=$(echo "$CHECK" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('target','') or '')")

if [ "$ACTION" != "apply" ]; then
  echo "release.sh: no action ($ACTION)"
  exit 0
fi

echo "release.sh: deploying $TARGET"

# Step 3 — topology discovery and secret sync
# Reads [[dependent_project]] from the leader's lens.toml, clones each
# sibling to collect API keys and dataset references, then calls
# fly secrets set for every secret that has a CI env var available.
# Secrets without a CI env var are left unchanged (additive only).
# The Fly app name is auto-detected from fly.toml.
$PY sync

# Step 4 — build params
APPLY=$($PY apply --to "$TARGET" --json)

LENS_REPO_URL=$(echo "$APPLY" | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['lens_repo_url'])")
LENS_CLONE_DIR=$(mktemp -d)
LENS_CLONE="$LENS_CLONE_DIR/lens"
trap 'rm -rf "$LENS_CLONE_DIR"' EXIT

echo "release.sh: cloning Lens repo from $LENS_REPO_URL (tag: $TARGET)"
git init "$LENS_CLONE"
git -C "$LENS_CLONE" remote add origin "$LENS_REPO_URL"
git -C "$LENS_CLONE" fetch --depth 1 origin "refs/tags/$TARGET"
git -C "$LENS_CLONE" checkout FETCH_HEAD

# Step 5 — deploy
# Uses the cloned Lens repo as the Docker build context so deploy/Dockerfile
# has access to the full source tree (pyproject.toml, lens/, datasets/, UI).
flyctl deploy \
  --app "$FLY_APP" \
  --build-arg "LENS_VERSION=$TARGET" \
  "$LENS_CLONE" \
  --config "$FLY_TOML" \
  --dockerfile "$LENS_CLONE/deploy/Dockerfile"

echo "release.sh: deploy of $TARGET succeeded"
