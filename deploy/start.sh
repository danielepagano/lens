#!/bin/bash
set -euo pipefail

# ---- 1. SSH setup for GitLab ----
mkdir -p /root/.ssh
chmod 700 /root/.ssh

echo "$GITLAB_DEPLOY_KEY" > /root/.ssh/deploy_key
chmod 600 /root/.ssh/deploy_key

ssh-keyscan -t ed25519,rsa gitlab.com > /root/.ssh/known_hosts 2>/dev/null
chmod 600 /root/.ssh/known_hosts

cat > /root/.ssh/config <<EOF
Host gitlab.com
  HostName gitlab.com
  User git
  IdentityFile /root/.ssh/deploy_key
  IdentitiesOnly yes
  StrictHostKeyChecking yes
  UserKnownHostsFile /root/.ssh/known_hosts
EOF
chmod 600 /root/.ssh/config

# ---- 2. Git config (needed for lens checkpoint) ----
git config --global user.name "Lens Server"
git config --global user.email "lens@fly.io"

# ---- 3. Project repo: clone if missing, skip if present ----
REPO_DIR="${LENS_PROJECT_DIR:-/data/repo}"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning project repo…"
    git clone "$PROJECT_REPO_URL" "$REPO_DIR"
else
    echo "Project repo found on volume."
    cd "$REPO_DIR"
    git fetch origin || echo "Warning: git fetch failed"
    git merge --ff-only origin/$(git rev-parse --abbrev-ref HEAD) \
        || echo "Warning: could not fast-forward (diverged or detached HEAD)"
fi

# ---- 4. Validate ----
if [ ! -f "$REPO_DIR/lens.toml" ]; then
    echo "ERROR: $REPO_DIR/lens.toml not found" >&2
    exit 1
fi

# ---- 5. Start Caddy (background) ----
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &

# ---- 6. Start Lens (foreground) ----
cd "$REPO_DIR"
exec lens serve --host 127.0.0.1 --port "${LENS_PORT:-8000}"
