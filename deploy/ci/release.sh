#!/bin/bash
set -euo pipefail

# Common CI release logic — shared by all provider-specific pipeline wrappers.
#
# Usage: release.sh --since <commit> --fly-app <name>
#
# Prerequisites (CI secrets / env vars — all required, checked every run):
#   FLY_API_TOKEN                                  flyctl deploy auth
#   GIT_REPO_DEPLOY_KEY_<LEADER_SLUG>              leader project clone at boot
#   GIT_REPO_DEPLOY_KEY_<DEPENDENT_NAME>           per [[dependent_project]]
#   DATASET_REPO_DEPLOY_KEY_<NAME>                 per [[dataset_repo]]
#   Any api_key_env from [[llm]] / [[image]] / [[speech]]
#
# Steps:
#   1. release_secrets.py check --json   →  blocking pre-flight (every commit)
#   2. lens release check --since <SHA> --json  →  decide apply or none
#   3. release_secrets.py sync             →  discover topology, sync Fly secrets
#   4. lens release apply --to <tag> --json      →  build params
#   5. flyctl deploy --build-arg LENS_VERSION=<tag>
#

SINCE=""
FLY_APP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --since)
      SINCE="$2"
      shift
      ;;
    --fly-app)
      FLY_APP="$2"
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
if [ -z "$FLY_APP" ]; then
  echo "release.sh: --fly-app is required" >&2
  exit 1
fi

# Step 1 — pre-flight secrets check (every commit, fail fast on drift)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/release_secrets.py" check --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
missing_env = [s['name'] for s in data.get('secrets', []) if not s['set_in_env']]
if missing_env:
    print('release.sh: FATAL — the following secrets are not set in CI environment:')
    for n in missing_env:
        print(f'  {n}')
    print('release.sh: set them as CI env vars and retry.')
    sys.exit(1)
else:
    print('release.sh: all secrets present in environment')
"

# Step 2 — check
CHECK=$(lens release check --since "$SINCE" --json)
ACTION=$(echo "$CHECK" | sed -n '1p' | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('action','none'))")
TARGET=$(echo "$CHECK" | sed -n '1p' | python3 -c \
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
python3 "$SCRIPT_DIR/release_secrets.py" sync --fly-app "$FLY_APP"

# Step 4 — build params
lens release apply --to "$TARGET" --json

# Step 5 — deploy
# On failure the flyctl error output (missing secret, build timeout, image
# issue, infra error) is captured in CI logs.  The exit code propagates and
# fails the pipeline step — no automated retry or webhook.
flyctl deploy --app "$FLY_APP" --build-arg LENS_VERSION="$TARGET" --remote-only

echo "release.sh: deploy of $TARGET succeeded"
