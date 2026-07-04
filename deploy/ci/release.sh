#!/bin/bash
set -euo pipefail

# Common CI release logic — shared by all provider-specific pipeline wrappers.
#
# Usage: release.sh --since <commit> --fly-app <name>
#
# Prerequisites (CI secrets / env vars):
#   FLY_API_TOKEN                                  required — flyctl deploy auth
#   DEPENDENT_PROJECT_DEPLOY_KEY_<NAME>            optional, per [[dependent_project]]
#   DATASET_REPO_DEPLOY_KEY_<NAME>                 optional, per [[dataset_repo]]
#   Any api_key_env from [[llm]] / [[image]] / [[speech]]  optional
#
# Steps:
#   1. lens release check --since <SHA> --json  →  decide apply or none
#   2. lens release secrets sync                →  discover topology, sync Fly secrets
#   3. lens release apply --to <tag> --json      →  build params
#   4. flyctl deploy --build-arg LENS_VERSION=<tag>
#
# Design docs/release-system.md Phase 4 for full architecture.

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

# Step 1 — check
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

# Step 2 — topology discovery and secret sync
# Reads [[dependent_project]] from the leader's lens.toml, clones each
# sibling to collect API keys and dataset references, then calls
# fly secrets set for every secret that has a CI env var available.
# Secrets without a CI env var are left unchanged (additive only).
lens release secrets sync --fly-app "$FLY_APP"

# Step 3 — build params
lens release apply --to "$TARGET" --json

# Step 4 — deploy
# On failure the flyctl error output (missing secret, build timeout, image
# issue, infra error) is captured in CI logs.  The exit code propagates and
# fails the pipeline step — no automated retry or webhook.
flyctl deploy --app "$FLY_APP" --build-arg LENS_VERSION="$TARGET" --remote-only

echo "release.sh: deploy of $TARGET succeeded"
