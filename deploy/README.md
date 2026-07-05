# Deployment

Lens deploys to [Fly.io](https://fly.io) as a single-machine app with a persistent volume. The `lens deploy` CLI command handles setup and deployment.

Project configuration (`lens.toml`, API keys, mounts): **[docs/configuration.md](../docs/configuration.md)**.

## Architecture

```
Internet → Fly Edge (TLS) → Caddy (Basic Auth, :8080) → Lens Server (localhost:8000)
                                                              ↓
                                                     /data/repos/ (Fly volume)
                                                         ↕ git pull/push
                                                      Git remotes (SSH)
```

- **Caddy** is the only listener — enforces Basic Auth and reverse-proxies to Lens.
- **Lens** binds to `127.0.0.1` only; never exposed directly.
- **Fly** terminates TLS at the edge; Caddy handles auth, not certificates.
- Project repos live on a persistent Fly volume at `/data/repos/<slug>/`.
- The Lens application (Python code, datasets, built UI) is baked into the Docker image.

One Fly app can serve one project or several — the setup is the same either way.

## Prerequisites

- [flyctl](https://fly.io/docs/flyctl/install/) installed and authenticated (`fly auth login`)
- Each project's `origin` set to an **SSH** remote URL (e.g. `git@github.com:org/repo.git`) — HTTPS is not supported; the machine authenticates with deploy keys only
- An SSH deploy key per project, registered on its Git host with read/write access
- LLM (and optional image / speech) API keys in your environment (matching each `api_key_env` in `lens.toml`)
- If any project uses an S3 mount: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`, `AWS_DEFAULT_REGION` in your environment; all projects must share the same S3 bucket

## Initial Setup

Run `lens deploy init` from the directory that will contain `fly.toml`:

**Single project** — run from inside the project directory (alongside `lens.toml`):

```bash
lens deploy init \
  --app my-campaign \
  --region lax \
  --user myname \
  --deploy-key ~/.ssh/my-campaign-deploy
```

**Multiple projects** — run from a parent directory containing project subdirectories:

```
projects/
  campaign-a/    ← lens.toml, origin = git@github.com:…/campaign-a.git
  campaign-b/    ← lens.toml, origin = git@gitlab.com:…/campaign-b.git
```

```bash
cd projects/
lens deploy init \
  --app my-campaigns \
  --region lax \
  --user myname \
  --deploy-key campaign-a=~/.ssh/key_a \
  --deploy-key campaign-b=~/.ssh/key_b
```

The `slug=path` pairs in `--deploy-key` select which projects to include — no directory scanning. You will be prompted for the Basic Auth password in both cases.

If you also use the release system, note that a Fly app serving multiple projects has only **one** deployed Lens version shared by all of them: exactly one project must be flagged `[release] app_leader = true` in its `lens.toml`, and only that project's `lens.toml`/CI governs upgrades for the whole app. `lens deploy init`/`add`/`push` validate this (and that sibling projects don't declare conflicting `[[dataset_repo]]` entries for the same name). See [Multi-project deployments](#multi-project-deployments) below for where `fly.toml` ends up and how commands find it.

`init` will:
1. Validate each project: SSH remote, S3-only mount (if any), same S3 bucket across all
2. Collect LLM, image, and speech API keys (each ``api_key_env`` in ``[[llm]]`` / ``[[image]]`` / ``[[speech]]``) plus S3 credentials from your current environment
3. Generate `fly.toml` in the current directory
4. Create the Fly app and a 1 GB persistent volume
5. Set all secrets on the Fly app

### Fly regions

Pick the region closest to you. Common choices: `lax` (Los Angeles), `ams` (Amsterdam), `lhr` (London), `fra` (Frankfurt), `iad` (Virginia). Full list: `fly platform regions`.

### Container environment (`fly.toml` `[env]`)

Set by `lens deploy init` (not secrets):

| Variable | Purpose |
|----------|---------|
| `LENS_CLOUD_DEPLOYED` | `1` — Lens rejects local filesystem `mount_point` values at runtime |
| `LENS_PROJECT_DIR` | Clone root on the Fly volume (default `/data/repos`) |
| `LENS_PROJECT_SLUGS` | Comma-separated project slugs served by this app |
| `LENS_PORT` | Uvicorn bind port behind Caddy (default `8000`) |
| `CADDY_PORT` | Caddy listen port (default `8080`) |

### Secrets

| Secret | Value |
|--------|-------|
| `CADDY_BASIC_AUTH_USER` / `CADDY_BASIC_AUTH_HASH` | Basic Auth credential |
| `GIT_REPO_DEPLOY_KEY_<SLUG>` | SSH deploy key per project (slug uppercased, hyphens→underscores) |
| `PROJECT_REPO_URL_<SLUG>` | Git remote URL per project |
| LLM / image / speech keys (e.g. `OPEN_ROUTER_API_KEY`, `A2E_TOKEN`, `XAI_API_KEY`) | From each project's ``[[llm]]`` / ``[[image]]`` / ``[[speech]]`` ``api_key_env``; deduplicated across blocks and projects |
| `AWS_*` | S3 credentials, if any project uses an S3 mount |
| `DATASET_REPO_DEPLOY_KEY_<NAME>` | SSH deploy key for a private ``[[dataset_repo]]`` (name uppercased, hyphens→underscores). E.g. a repo named ``lens-my-dataset`` uses env var ``DATASET_REPO_DEPLOY_KEY_LENS_MY_DATASET``. Optional in the desktop flow — external datasets are bundled into the Docker image, so the key is only needed for runtime ``/refresh`` updates. **Required** for private repos in a CI deploy where no local checkout exists to copy from. |

## Multi-project deployments

A Fly app serving several project repos needs exactly one `fly.toml`, and (if
you use the release system) exactly one `[release] app_leader = true`
project governing the shared Lens version. `fly.toml` can live in either of
two places:

1. **Bare parent directory** — `fly.toml` sits in a plain directory above the
   project subdirectories (the directory itself has no `lens.toml`). This is
   what `lens deploy init` generates by default when no project sets
   `app_leader = true`.
2. **Leader-colocated** — if exactly one of the projects passed to `lens
   deploy init` sets `[release] app_leader = true`, `fly.toml` is generated
   **inside that leader's own project directory** instead, so it's tracked
   and versioned by the leader's own git repo (no bare, ungitted directory
   holding your deployment config). Sibling projects stay where they are, as
   siblings of the leader's directory — not nested under it.

`lens deploy push` / `add` / `remove` (and `lens release check` / `apply`)
locate `fly.toml` automatically, in this order, so the same commands work
under either layout:

1. The current directory itself has `fly.toml`.
2. The current directory is inside a project (`lens.toml` at an ancestor)
   whose root also has `fly.toml`.
3. An immediate child of the current directory colocates `lens.toml` +
   `fly.toml` — this is what lets you run these commands from the
   **grandparent** directory (the folder containing the leader project and
   its siblings) in the leader-colocated layout, exactly like you would from
   the bare parent directory in layout 1.

Example: `~/projects/` contains `campaign-a/` (the release leader, holding
`campaign-a/fly.toml`) and `campaign-b/` (a sibling with no remote-tracking
requirement beyond being listed in `LENS_PROJECT_SLUGS`). Running `lens dev`,
`lens serve`, or `lens deploy push` from `~/projects/` works the same as
running them from inside `campaign-a/` — commands resolve the deployment
automatically either way. Sibling directories that aren't a Fly-tracked
project at all (no `lens.toml`, or a `lens.toml` never passed to `lens deploy
init`/`add`) are simply not part of `LENS_PROJECT_SLUGS` and are ignored by
`deploy`/`release`, even though `lens dev`/`serve` will still serve them
locally alongside the deployed ones.

Only the leader's own CI needs deployment access: a `FLY_API_TOKEN` secret to
run `flyctl deploy`, plus whatever git access it already has to check out its
own repo (which now includes `fly.toml`). It does not need credentials for
sibling project repos — those repos' `GIT_REPO_DEPLOY_KEY_<SLUG>` /
`PROJECT_REPO_URL_<SLUG>` secrets are already set on the Fly app itself (via
`lens deploy init`/`add` from the desktop), and the running container uses
them directly to clone/refresh each project on the volume. Sibling repos'
own CI, if any, should only call their project's `/refresh` endpoint — never
`flyctl deploy` — since only one project may control the shared Lens version.

## Deploying

Make sure all project repos are pushed to their remotes, then:

```bash
lens deploy push
```

Optional: `lens deploy push --mode fly` (default, Fly builder without Depot), `--mode depot`, or `--mode local` (build image on this machine with Docker, then push).

Run this from the directory containing `fly.toml`, from inside that project, or — in a multi-project deployment — from its parent directory; see [Multi-project deployments](#multi-project-deployments) for exactly how `fly.toml` is located. **`push` re-syncs all LLM, image, and speech `api_key_env` secrets** from your current shell into the Fly app (then deploys), so you can add a new ``[[image]]`` or ``[[speech]]`` block, export the key locally, and run `lens deploy push` without re-running `init`.

`push` also re-syncs any `DATASET_REPO_DEPLOY_KEY_<NAME>` secrets from your current environment, so adding a new ``[[dataset_repo]]`` entry (or rotating a deploy key) only requires setting the env var locally and running `lens deploy push` — no need to re-run `init`.

On first boot, `start.sh` clones each repo onto the volume. On subsequent boots it fast-forwards from `origin`. The volume is never touched by a redeploy.

## Managing Projects

To add a project to an existing deployment (run from wherever `fly.toml` resolves — see [Multi-project deployments](#multi-project-deployments)):

```bash
lens deploy add campaign-c --deploy-key ~/.ssh/key_c
lens deploy push
```

To remove one:

```bash
lens deploy remove campaign-b
lens deploy push
```

`add` sets the new project's secrets and updates `fly.toml`. `remove` clears them. `push` redeploys with the new configuration. Shared provider keys (`api_key_env` values) are not cleared on remove — they may still be needed by remaining projects.

## Operational Reference

### Updating Lens (code, datasets, UI)

Pull the latest Lens code locally, then:

```bash
lens deploy push
```

This rebuilds the Docker image. Project repos on the volume are untouched.

External datasets referenced in deployed projects (e.g. a private `lens-dnd` tree) are copied into the image under `datasets/<name>/` during `push`, including any Python extension package and `prompts/` declared in that dataset’s `lens.toml`. No separate pip install on the server.

### Updating project content

Push local changes to the Git remote, then use the **Refresh** button in the web UI (or `POST /refresh` on the API). The server does a `git fetch` + fast-forward merge. If there are uncommitted changes on the server, checkpoint first.

### Volume

The Fly volume at `/data` persists across restarts, redeploys, and machine suspend/resume. It is tied to one machine in one region.

**Recovery**: The volume is not replicated. Your Git remotes are the durable copies. Use `lens checkpoint` (via the web UI) to push work off the server before doing anything risky. Fly volume snapshots provide additional disaster recovery (`fly volumes snapshots list`).

### Machine lifecycle

The default config suspends the machine after idle time and resumes it on the next request (a few seconds of wake latency). To keep it always on, set `min_machines_running = 1` in `fly.toml` and redeploy.

### SSH into the machine

```bash
fly ssh console --app my-campaign
```

### Logs

```bash
fly logs --app my-campaign
```

### Changing the password

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'new-password', bcrypt.gensalt()).decode())"
fly secrets set CADDY_BASIC_AUTH_HASH='$2b$12$...' --app my-campaign
```

The machine restarts automatically after secret changes.

### Scaling

Edit `[[vm]]` in `fly.toml` and redeploy:

```toml
[[vm]]
  size = "shared-cpu-2x"
  memory = "1024mb"
```

### Custom domain

```bash
fly certs add lens.example.com --app my-campaign
# Point DNS: CNAME lens.example.com → my-campaign.fly.dev
```

## CI-driven deploy (no desktop)

A project using the release system (`[release] enabled = true`) can deploy new
Lens versions entirely from CI — no local `lens deploy push` needed.

### Topology: `[[dependent_project]]`

In a multi-project Fly app, the release leader's `lens.toml` declares sibling
projects via a `[[dependent_project]]` array (one entry per sibling). The
leader's CI uses this to discover the full topology — no sibling directories
on disk required:

```toml
[[dependent_project]]
name    = "campaign-b"
git_url = "git@gitlab.com:org/campaign-b.git"
ref     = "main"

[[dependent_project]]
name    = "campaign-c"
git_url = "git@github.com:org/campaign-c.git"
ref     = "main"
```

Adding a new sibling means editing this array, committing, and pushing — CI
picks it up automatically.

### How it works

1. A user clicks **Update** in the Lens UI, which writes `requested_version` +
   `requested_from_commit` into `lens.toml` (uncommitted).
2. Their next **Checkpoint** commits and pushes both fields to the remote.
3. The push triggers the release leader's CI pipeline (`release.sh`), which:
   a. Runs `deploy/ci/release_secrets.py check --json` — verifies every
      required secret is present in the CI environment (blocks on any miss).
   b. Runs `deploy/ci/release_secrets.py check-release --since <SHA> --json`
      — parent-hash match (standalone, no lens package needed).
   c. Runs `deploy/ci/release_secrets.py sync` — reads `[[dependent_project]]`
      from the leader's `lens.toml`, clones each sibling to read its API keys
      and dataset references, and pushes the needed Fly secrets (additive only
      — never deletes; Fly app name auto-detected from `fly.toml`).
   d. Runs `deploy/ci/release_secrets.py apply --to <tag> --json` — prints
      build params (standalone, no lens package needed).
   e. Runs `flyctl deploy --build-arg LENS_VERSION=<tag>`.
4. The new container boots, `start.sh` clones/fast-forwards all project repos
   and dataset repos from the freshly-synced secrets, and the app is live on
   the new version.

CI **never writes to git** — the check + sync + deploy flow is read-only
(except for `fly secrets set`, which writes to the Fly app's secret store,
not to any git repo). Deploy errors are surfaced in the CI run logs; checking
them for the failure reason (missing `FLY_API_TOKEN`, build timeout, etc.)
is the intended debugging workflow.

### Prerequisites

| Secret | Where | Purpose |
|--------|-------|---------|
| `FLY_API_TOKEN` | CI secret (required) | Authenticate `flyctl deploy` and `fly secrets set` |
| `GIT_REPO_DEPLOY_KEY_<SLUG>` | CI secret (required, per project) | SSH deploy key for the leader + each `[[dependent_project]]` repo |
| `DATASET_REPO_DEPLOY_KEY_<NAME>` | CI secret (optional, per dataset) | SSH deploy key for a `[[dataset_repo]]` |
| Any `api_key_env` from `lens.toml` | CI secret (optional) | LLM / image / speech API keys |
| Git checkout history | `fetch-depth: 0` | `release_secrets.py check-release` reads parent hashes |

Secrets discovered by `release.sh` but without a matching CI env var are
**left unchanged on Fly** — never deleted or overwritten with empty.

No Basic Auth credentials for the deployed app are needed in CI — CI never
talks to the running container.

### Pipeline templates

| File | Purpose |
|------|---------|
| `deploy/ci/release.sh` | Shared shell script: secrets check → check-release → sync → apply → deploy |
| `deploy/ci/release_secrets.py` | Standalone Python (zero deps): secrets check and sync |
| `deploy/ci/github-release.yml` | GitHub Actions: trigger, calls `release.sh` |
| `deploy/ci/gitlab-release.yml` | GitLab CI: trigger, calls `release.sh` |

Copy the relevant provider template into your project repository and set the
required secrets. The desktop `lens deploy push` flow and CI-driven deploy
are alternatives against the same Fly app — do not run both for the same
build. A one-time `lens deploy init` from desktop is still needed for the
initial Fly app creation and volume setup; after that, CI handles all
routine upgrades and topology changes.

## Files

| File | Purpose |
|------|---------|
| `deploy/Dockerfile` | Multi-stage build: Python + Node builder → slim runtime with git + Caddy |
| `deploy/Caddyfile` | Caddy config: Basic Auth + reverse proxy with SSE-safe flushing |
| `deploy/start.sh` | Container entrypoint: SSH setup, repo clone/update, starts Caddy + Lens |
| `deploy/ci/release.sh` | Shared CI release script: check + apply + `flyctl deploy` |
| `deploy/ci/release_secrets.py` | Standalone Python (zero deps): secrets check and sync for CI |
| `deploy/ci/github-release.yml` | GitHub Actions pipeline template (calls `release.sh`) |
| `deploy/ci/gitlab-release.yml` | GitLab CI pipeline template (calls `release.sh`) |
| `fly.toml` | Generated by `lens deploy init` — in the project directory (single-project), a bare parent directory, or the release leader's project directory (see [Multi-project deployments](#multi-project-deployments)) |

## Local Deploy (Caddy on your machine)

Run Lens on your own machine and expose it safely via Caddy (HTTPS + Basic Auth). Lens must only bind to localhost; Caddy is the only public entrypoint.

**1. Run Lens:**

```bash
lens serve --host 127.0.0.1 --port 8000
```

**2. Generate a password hash:**

```bash
caddy hash-password --plaintext 'choose-a-strong-password'
```

**3. Create a Caddyfile:**

```caddyfile
lens.example.com {
  encode gzip zstd

  basic_auth {
    myuser <paste-hash-here>
  }

  reverse_proxy 127.0.0.1:8000 {
    flush_interval -1
  }
}
```

`flush_interval -1` is required for SSE streaming.

**4. Start Caddy:**

```bash
caddy run --config ./Caddyfile --adapter caddyfile
```

For external access, point `lens.example.com` to your machine's IP and forward TCP 443 from your router. For DNS-01 certificates or dynamic DNS, use a custom Caddy build with the appropriate provider module.
