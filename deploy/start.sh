#!/bin/bash
set -euo pipefail

# All deployments (single and multi-project) use the same boot sequence.
# LENS_PROJECT_SLUGS lists the projects to clone; each has its own deploy
# key and repo URL stored as Fly secrets (GIT_REPO_DEPLOY_KEY_<SLUG> /
# PROJECT_REPO_URL_<SLUG>).  Single-project is the multi case with one slug.

if [ -z "${LENS_PROJECT_SLUGS:-}" ]; then
    echo "ERROR: LENS_PROJECT_SLUGS is not set" >&2
    exit 1
fi

REPOS_DIR="${LENS_PROJECT_DIR:-/data/repos}"

# ---- 1. SSH setup ----
mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/known_hosts
chmod 600 /root/.ssh/known_hosts

# ---- 2. Git config (needed for lens checkpoint) ----
git config --global user.name "Lens Server"
git config --global user.email "lens@fly.io"

mkdir -p "$REPOS_DIR"

# ---- 3. Clone or update each project repo ----
IFS=',' read -ra SLUGS <<< "$LENS_PROJECT_SLUGS"
for SLUG in "${SLUGS[@]}"; do
    SLUG_KEY=$(echo "$SLUG" | tr '[:lower:]-' '[:upper:]_')
    DEPLOY_KEY_VAR="GIT_REPO_DEPLOY_KEY_${SLUG_KEY}"
    REPO_URL_VAR="PROJECT_REPO_URL_${SLUG_KEY}"
    DEPLOY_KEY="${!DEPLOY_KEY_VAR:-}"
    REPO_URL="${!REPO_URL_VAR:-}"

    if [ -z "$DEPLOY_KEY" ]; then
        echo "ERROR: Fly secret $DEPLOY_KEY_VAR is not set" >&2
        exit 1
    fi
    if [ -z "$REPO_URL" ]; then
        echo "ERROR: Fly secret $REPO_URL_VAR is not set" >&2
        exit 1
    fi

    KEY_FILE="/root/.ssh/deploy_key_${SLUG_KEY}"
    echo "$DEPLOY_KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"

    SSH_LINE=$(/app/.venv/bin/python -c "
from lens.core.git_ssh_remote import parse_git_ssh_remote
h, p = parse_git_ssh_remote('$REPO_URL')
print(f'{h}\t{p}')
")
    GIT_SSH_HOST="${SSH_LINE%%	*}"
    GIT_SSH_PORT="${SSH_LINE##*	}"

    if [ "$GIT_SSH_PORT" = "22" ]; then
        ssh-keyscan -t ed25519,rsa "$GIT_SSH_HOST" >> /root/.ssh/known_hosts 2>/dev/null
    else
        ssh-keyscan -t ed25519,rsa -p "$GIT_SSH_PORT" "$GIT_SSH_HOST" >> /root/.ssh/known_hosts 2>/dev/null
    fi

    GIT_SSH_CMD="ssh -i $KEY_FILE -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/root/.ssh/known_hosts"
    PROJECT_REPO_DIR="$REPOS_DIR/$SLUG"

    if [ ! -d "$PROJECT_REPO_DIR/.git" ]; then
        echo "Cloning $SLUG…"
        GIT_SSH_COMMAND="$GIT_SSH_CMD" git clone "$REPO_URL" "$PROJECT_REPO_DIR"
    else
        echo "Project $SLUG found on volume."
        GIT_SSH_COMMAND="$GIT_SSH_CMD" git -C "$PROJECT_REPO_DIR" fetch origin \
            || echo "Warning: git fetch failed for $SLUG"
        git -C "$PROJECT_REPO_DIR" merge --ff-only \
            "origin/$(git -C "$PROJECT_REPO_DIR" rev-parse --abbrev-ref HEAD)" \
            || echo "Warning: could not fast-forward $SLUG"
    fi

    # Persist the SSH command so all subsequent git operations in this repo
    # (checkpoint, refresh) use the right deploy key without a global SSH config.
    git -C "$PROJECT_REPO_DIR" config core.sshCommand "$GIT_SSH_CMD"

    if [ ! -f "$PROJECT_REPO_DIR/lens.toml" ]; then
        echo "ERROR: $PROJECT_REPO_DIR/lens.toml not found" >&2
        exit 1
    fi
done

# ---- 4. Start Caddy (background) ----
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &

# ---- 5. Start Lens (foreground) ----
# REPOS_DIR contains one subdirectory per project; discover_projects() finds them all.
cd "$REPOS_DIR"
exec lens serve --host 127.0.0.1 --port "${LENS_PORT:-8000}"
