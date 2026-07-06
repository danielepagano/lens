#!/bin/bash
set -euo pipefail

# All deployments (single and multi-project) use the same boot sequence.
# Project slugs are derived from PROJECT_REPO_URL_<SLUG_KEY> Fly secrets;
# each slug also needs GIT_REPO_DEPLOY_KEY_<SLUG_KEY> (optional for public
# repos) and PROJECT_REPO_URL_<SLUG_KEY> (always set by lens deploy init/add).

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
SLUGS=()
for VAR in "${!PROJECT_REPO_URL_@}"; do
    KEY="${VAR#PROJECT_REPO_URL_}"
    SLUG=$(echo "$KEY" | tr '[:upper:]_' '[:lower:]-')
    SLUGS+=("$SLUG")
done
if [ ${#SLUGS[@]} -eq 0 ]; then
    echo "ERROR: no PROJECT_REPO_URL_* secrets found" >&2
    exit 1
fi
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

# ---- 4. Clone or update shared dataset repos ----
DATASET_DIR="$REPOS_DIR/_datasets"
mkdir -p "$DATASET_DIR"
: > /tmp/_ds_seen.txt
for SLUG in "${SLUGS[@]}"; do
    PROJECT_FILE="$REPOS_DIR/$SLUG/lens.toml"
    [ ! -f "$PROJECT_FILE" ] && continue

    /app/.venv/bin/python -c "
import tomllib, sys
with open('$PROJECT_FILE', 'rb') as f:
    cfg = tomllib.load(f)
for entry in cfg.get('dataset_repo', []):
    if isinstance(entry, dict) and entry.get('name') and entry.get('git_url'):
        print(f\"{entry['name']}|{entry['git_url']}|{entry.get('ref', 'main')}\")
" 2>/dev/null | while IFS='|' read -r DS_NAME DS_URL DS_REF; do
        if grep -qx "$DS_NAME" /tmp/_ds_seen.txt 2>/dev/null; then
            continue
        fi
        echo "$DS_NAME" >> /tmp/_ds_seen.txt

        DS_KEY=$(echo "$DS_NAME" | tr '[:lower:]-' '[:upper:]_')
        DS_DEPLOY_KEY_VAR="DATASET_REPO_DEPLOY_KEY_${DS_KEY}"
        DS_DEPLOY_KEY="${!DS_DEPLOY_KEY_VAR:-}"

        DS_DIR="$DATASET_DIR/$DS_NAME"
        DS_SSH_CMD="ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/root/.ssh/known_hosts"

        if [ -n "$DS_DEPLOY_KEY" ]; then
            DS_KEY_FILE="/root/.ssh/dataset_deploy_key_${DS_KEY}"
            echo "$DS_DEPLOY_KEY" > "$DS_KEY_FILE"
            chmod 600 "$DS_KEY_FILE"
            DS_SSH_CMD="ssh -i $DS_KEY_FILE -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/root/.ssh/known_hosts"
        fi

        # Scan SSH host key for this dataset repo
        DS_SSH_LINE=$(/app/.venv/bin/python -c "
from lens.core.git_ssh_remote import parse_git_ssh_remote
try:
    h, p = parse_git_ssh_remote('$DS_URL')
    print(f'{h}\t{p}')
except ValueError:
    pass
" 2>/dev/null)
        if [ -n "$DS_SSH_LINE" ]; then
            DS_SSH_HOST="${DS_SSH_LINE%%	*}"
            DS_SSH_PORT="${DS_SSH_LINE##*	}"
            if [ "$DS_SSH_PORT" = "22" ]; then
                ssh-keyscan -t ed25519,rsa "$DS_SSH_HOST" >> /root/.ssh/known_hosts 2>/dev/null
            else
                ssh-keyscan -t ed25519,rsa -p "$DS_SSH_PORT" "$DS_SSH_HOST" >> /root/.ssh/known_hosts 2>/dev/null
            fi
        fi

        if [ ! -d "$DS_DIR/.git" ]; then
            echo "Cloning dataset $DS_NAME…"
            GIT_SSH_COMMAND="$DS_SSH_CMD" git clone --depth 1 "$DS_URL" "$DS_DIR" 2>/dev/null \
                || echo "Warning: could not clone dataset '$DS_NAME' from $DS_URL (add DATASET_REPO_DEPLOY_KEY_${DS_KEY} Fly secret if private)"
        else
            echo "Dataset $DS_NAME found on volume."
            GIT_SSH_COMMAND="$DS_SSH_CMD" git -C "$DS_DIR" fetch origin 2>/dev/null \
                || echo "Warning: could not fetch dataset '$DS_NAME' from $DS_URL"
            git -C "$DS_DIR" merge --ff-only "origin/$DS_REF" \
                || echo "Warning: could not fast-forward dataset '$DS_NAME'"
        fi
    done
done

# ---- 5. Start Caddy (background) ----
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &

# ---- 6. Start Lens (foreground) ----
# REPOS_DIR contains one subdirectory per project; discover_projects() finds them all.
cd "$REPOS_DIR"
exec lens serve --host 127.0.0.1 --port "${LENS_PORT:-8000}"
