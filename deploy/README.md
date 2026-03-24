# Deployment

Lens deploys to [Fly.io](https://fly.io) as a single-machine app with a persistent volume for the project repo. The `lens deploy` CLI command handles setup and deployment.

## Architecture

```
Internet → Fly Edge (TLS) → Caddy (Basic Auth, :8080) → Lens Server (localhost:8000)
                                                              ↓
                                                     /data/repo (Fly volume)
                                                         ↕ git pull/push
                                                      GitLab remote
```

- **Caddy** is the only listener — enforces Basic Auth and reverse-proxies to Lens.
- **Lens** binds to `127.0.0.1` only; never exposed directly.
- **Fly** terminates TLS at the edge; Caddy handles auth, not certificates.
- The **project repo** lives on a persistent Fly volume at `/data/repo`.
- The **Lens application** (Python code, datasets, built UI) is baked into the Docker image.

## Prerequisites

- [flyctl](https://fly.io/docs/flyctl/install/) installed and authenticated (`fly auth login`)
- A GitLab deploy key (SSH key pair) with write access to the project repo
- LLM API key(s) set in your environment (matching `api_key_env` in `lens.toml`)
- If using S3 mount: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`, `AWS_DEFAULT_REGION` set in your environment

## Initial Setup

From your project directory (the one with `lens.toml`):

```bash
lens deploy init \
  --app my-project \
  --region lax \
  --user myname \
  --deploy-key ~/.ssh/my-project-deploy
```

You will be prompted for the Basic Auth password. This command:

1. Reads the git remote URL from your project repo
2. Hashes the password (bcrypt, Caddy-compatible)
3. Reads the deploy key file
4. Collects LLM API keys and S3 credentials from your current environment
5. Generates `fly.toml` in your project directory
6. Creates the Fly app and a 1 GB persistent volume
7. Sets all secrets on the Fly app

### Secrets

Secrets are split into two categories:

| Category | Secrets | Source |
|----------|---------|--------|
| **Project-specific** | `CADDY_BASIC_AUTH_USER`, `CADDY_BASIC_AUTH_HASH`, `GITLAB_DEPLOY_KEY` | From `--user`, `--password`, `--deploy-key` flags |
| **Reusable** | LLM API keys (e.g. `OPEN_ROUTER_API_KEY`), `AWS_*` credentials | Pulled from your current shell environment |

Reusable secrets are read from whatever is set in your env at init time. If you use the same LLM key or S3 bucket across projects, they carry over automatically.

### Fly regions

Pick the region closest to you. Common choices: `lax` (Los Angeles), `ams` (Amsterdam), `lhr` (London), `fra` (Frankfurt), `iad` (Virginia). Full list: `fly platform regions`.

## Deploying

```bash
lens deploy push
```

This runs `fly deploy` with the Lens repo as the Docker build context and your project's `fly.toml` as config. It builds a fresh image with the latest Lens code, datasets, and UI, then replaces the running machine. The volume (project repo) is untouched.

### First deploy

On the first boot, `start.sh` clones the project repo from GitLab onto the empty volume. **Make sure your project is pushed to the remote before the first deploy.**

### Subsequent deploys

On subsequent boots the existing repo on the volume is reused (only a `git fetch` is attempted). No data is lost.

## Updating

### Updating Lens (code, datasets, UI)

Pull the latest Lens code locally, then re-run:

```bash
lens deploy push
```

This rebuilds the Docker image. The project repo on the volume is not touched.

### Updating project content on the server

Push your local changes to GitLab, then use the **Refresh** button in the web UI (or call `POST /refresh` on the API). The server does a `git fetch` + fast-forward merge. If there are uncommitted changes on the server, refresh will fail — checkpoint first.

## Operational Reference

### Volume

The Fly volume at `/data` persists across restarts, redeploys, and machine suspend/resume. It is tied to one machine in one region.

**Recovery**: The volume is not replicated. GitLab is the durable copy. Use `lens checkpoint` (via the web UI) to push work off the server. Fly volume snapshots provide additional disaster recovery (`fly volumes snapshots list`).

### Machine lifecycle

The default config uses `auto_stop_machines = "suspend"` with `min_machines_running = 0`. The machine suspends after idle time and resumes on the next request (a few seconds of wake latency). To keep it always on, set `min_machines_running = 1` in `fly.toml` and redeploy.

### SSH into the machine

```bash
fly ssh console --app my-project
```

### Logs

```bash
fly logs --app my-project
```

### Changing the password

```bash
# Generate a new hash
python -c "import bcrypt; print(bcrypt.hashpw(b'new-password', bcrypt.gensalt()).decode())"

# Update the secret
fly secrets set CADDY_BASIC_AUTH_HASH='$2b$12$...' --app my-project
```

The machine restarts automatically after secret changes.

### Scaling

To change VM size or memory, edit `[[vm]]` in your project's `fly.toml`:

```toml
[[vm]]
  size = "shared-cpu-2x"
  memory = "1024mb"
```

Then `lens deploy push`.

### Custom domain

```bash
fly certs add lens.example.com --app my-project
# Then point DNS: CNAME lens.example.com → my-project.fly.dev
```

Fly handles TLS for the custom domain. No Caddy config changes needed.

## Files

| File | Purpose |
|------|---------|
| `deploy/Dockerfile` | Multi-stage build: Python + Node builder → slim runtime with git + Caddy |
| `deploy/Caddyfile` | Caddy config: Basic Auth + reverse proxy with SSE-safe flushing |
| `deploy/start.sh` | Container entrypoint: SSH setup, repo clone, starts Caddy + Lens |
| `<project>/fly.toml` | Generated into the project repo by `lens deploy init` |
