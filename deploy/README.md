# Deployment

Lens deploys to [Fly.io](https://fly.io) as a single-machine app with a persistent volume. This deploy is designed to allow multiple projects for a single user and need under the $5/mo minimum required to be billed by fly... so it's a free server!

## Table of contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Setup path: nothing → live app with CI releases](#setup-path)
  1. [Desktop init — create the Fly app](#1-desktop-init--create-the-fly-app)
  2. [Release init — configure the CI pipeline](#2-release-init--configure-the-ci-pipeline)
  3. [Set CI secrets](#3-set-ci-secrets)
- [Deploying](#deploying)
  - [Desktop push](#desktop-push)
  - [CI release pipeline](#ci-release-pipeline)
- [Managing projects](#managing-projects)
- [Operations](#operations)
- [Tools reference](#tools-reference)
- [Local deploy (Caddy on your machine)](#local-deploy-caddy-on-your-machine)

---

## Overview

### Architecture

```
Internet → Fly Edge (TLS) → Caddy (Basic Auth, :8080) → Lens Server (localhost:8000)
                                                               ↓
                                                      /data/repos/ (Fly volume)
                                                          ↕ git pull/push
                                                       Git remotes (SSH)
```

- **Caddy** is the only public listener — enforces Basic Auth and reverse-proxies to Lens.
- **Lens** binds to `127.0.0.1` only; never exposed directly.
- **Fly** terminates TLS at the edge; Caddy handles auth, not certificates.
- Project repos live on a persistent Fly volume at `/data/repos/<slug>/`.
- The Lens application (Python code, datasets, built UI) is baked into the Docker image.
- One Fly app can serve one project or several — the setup is the same either way.

### Two deployment paths

| Path | Who runs it | Secrets source | Use case |
|------|-------------|----------------|----------|
| **Desktop mode** — `lens deploy` | You (local machine) | Your shell env | All non-release deployments; single-project or multi-project without `[release]` enabled |
| **Release mode** — `lens release` + CI pipeline | GitHub Actions / GitLab CI | CI repository secrets | Shared deployments where `[release]` is enabled, automated Lens version upgrades after users click **Update** |

Both systems deploy to the same Fly app; they are alternatives for different workflows. A one-time `lens deploy init` from desktop is always needed for initial Fly app creation and volume setup — after that, all routine upgrades can be done from CI.

---

## Setup path

The path from nothing to a live app with CI-based releases:

```
[Your machine]                              [Remote Git host]
     |                                           |
     0. lens init                                 |
     |   creates project (lens.toml, narrative/)  |
     |   git init && git add && git commit         |
     |                                           |
     +-----> git remote add origin <SSH URL> -----+
     |                                           |
     1. lens deploy init                          |
     |   creates Fly app, volume, secrets         |
     |   writes fly.toml                          |
     |                                           |
     2. lens release init --leader               |
     |   enables [release], discovers topology    |
     |   installs CI pipeline templates           |
     |                                           |
     |                                 3. Set CI secrets   |
     |                                   (FLY_API_TOKEN,    |
     |                                    GIT_REPO_DEPLOY_, |
     |                                    API keys)          |
     |                                           |
     +----> lens deploy push (once) --------------+
     |                                           |
                                          Next push triggers
                                          automated release
```

### 1. Desktop init — create the Fly app

Run `lens deploy init` from the directory that will contain `fly.toml`.

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

The `slug=path` pairs in `--deploy-key` select which projects to include — no directory scanning. You are prompted for the Basic Auth password in both cases. When `[release] enabled` is true on any project, any `lens deploy` subcommand besides `init` now refuses to run and instructs you to use the equivalent `lens release` command (e.g., `lens release add`, `lens release remove`, `lens release push`).

`init` will:
1. Validate each project: SSH remote, S3-only mount (if any), same S3 bucket across all
2. Collect LLM, image, and speech API keys (each `api_key_env` in `[[llm]]` / `[[image]]` / `[[speech]]`) plus S3 credentials from your current environment
3. Generate `fly.toml` in the current directory
4. Create the Fly app and a 1 GB persistent volume
5. Set all secrets on the Fly app

#### Secrets set by `lens deploy init`

| Secret | Value |
|--------|-------|
| `CADDY_BASIC_AUTH_USER` / `CADDY_BASIC_AUTH_HASH` | Basic Auth credential (you provide the password; `init` hashes it) |
| `GIT_REPO_DEPLOY_KEY_<SLUG>` | SSH deploy key per project (slug uppercased, hyphens→underscores) |
| `PROJECT_REPO_URL_<SLUG>` | Git remote URL per project |
| LLM / image / speech keys (e.g. `OPEN_ROUTER_API_KEY`) | From each project's `api_key_env`; deduplicated across blocks and projects |
| `AWS_*` | S3 credentials, if any project uses an S3 mount |
| `DATASET_REPO_DEPLOY_KEY_<NAME>` | SSH deploy key for a private `[[dataset_repo]]` (optional in desktop flow — datasets are bundled into the image; needed for runtime `/refresh` updates) |

#### Deploy keys

Each project pushed to a SSH git remote needs an SSH deploy key so the Fly
container can clone and push to the repo.

**Create a key pair** (one per project or dataset repo):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/my-campaign-deploy -N ""
```

**Register the public key** on your Git host with **write** access:

| Host | Location |
|------|----------|
| GitHub | Repository → Settings → Deploy keys → Add deploy key. Check **Allow write access**. |
| GitLab | Repository → Settings → Repository → Deploy keys → Add. Check **Grant write permissions**. |

The **private** key (`~/.ssh/my-campaign-deploy`) is passed to
`lens deploy init --deploy-key <path>` which stores it as
`GIT_REPO_DEPLOY_KEY_<SLUG>` on Fly. The container uses it at boot to
authenticate when cloning repos.

**For dataset repos** (`[[dataset_repo]]`), same process — create a key,
register its public half on the Git host, and either:
- Pass it to `lens deploy init` (it reads deploy keys from the active project's
  env or auto-discovers them), or
- Set `DATASET_REPO_DEPLOY_KEY_<NAME>` directly on Fly (see
  [Managing secrets](#managing-secrets)).

#### Container environment (fly.toml `[env]`)

| Variable | Purpose |
|----------|---------|
| `LENS_CLOUD_DEPLOYED` | `1` — Lens rejects local filesystem `mount_point` values at runtime |
| `LENS_PROJECT_DIR` | Clone root on the Fly volume (default `/data/repos`) |
| `LENS_PROJECT_SLUGS` | Comma-separated project slugs served by this app |
| `LENS_PORT` | Uvicorn bind port behind Caddy (default `8000`) |
| `CADDY_PORT` | Caddy listen port (default `8080`) |

#### Fly regions

Pick the region closest to you. Common choices: `lax` (Los Angeles), `ams` (Amsterdam), `lhr` (London), `fra` (Frankfurt), `iad` (Virginia). Full list: `fly platform regions`.

#### Multi-project deployments

A Fly app serving several project repos needs exactly one `fly.toml`, and (if
you use the release system) exactly one `[release] app_leader = true` project
governing the shared Lens version. `fly.toml` can live in either of two places:

1. **Bare parent directory** — `fly.toml` sits in a plain directory above the
   project subdirectories (the directory itself has no `lens.toml`). This is
   what `lens deploy init` generates by default when no project sets
   `app_leader = true`.
2. **Leader-colocated** — if exactly one of the projects passed to `lens deploy
   init` sets `[release] app_leader = true`, `fly.toml` is generated **inside
   that leader's own project directory** instead, so it's tracked and versioned
   by the leader's own git repo (no bare, ungitted directory holding your
   deployment config). Sibling projects stay where they are, as siblings of the
   leader's directory — not nested under it.

`lens deploy push` / `add` / `remove` (and all `lens release` commands)
locate `fly.toml` automatically:

1. The current directory itself has `fly.toml`.
2. The current directory is inside a project (`lens.toml` at an ancestor) whose
   root also has `fly.toml`.
3. An immediate child of the current directory colocates `lens.toml` +
   `fly.toml` — this lets you run commands from the **grandparent** directory
   in the leader-colocated layout.

Only the leader's own CI needs deployment access: a `FLY_API_TOKEN` secret to
run `flyctl deploy`, plus whatever git access it already has to check out its
own repo (which now includes `fly.toml`). Sibling projects' repos are cloned
at container boot via the `GIT_REPO_DEPLOY_KEY_<SLUG>` secrets already set on
the Fly app. Sibling repos' own CI, if any, should only call their project's
`/refresh` endpoint — never `flyctl deploy` — since only one project controls
the shared Lens version.

---

### 2. Release init — configure the CI pipeline

After `lens deploy init` has created the Fly app, run `lens release init` from
the **release leader's project directory** (the project that will own the CI
pipeline and the shared Lens version), or from the **parent deploy directory**
(where `fly.toml` lives) with `--as-leader <slug>`:

```bash
# From the leader's project directory:
lens release init --leader

# Or from the parent deploy directory (fly.toml lives here):
lens release init --as-leader campaign-a
```

Without `--leader`, the project is a participant with no CI ownership. When
running from a parent deploy directory that has multiple projects, use
`--as-leader <slug>` to specify which one becomes the leader — without it you
get a helpful error listing the available slugs.

`lens release init` does four things:

1. **Enables `[release]`** — sets `enabled = true` and writes `lens_repo_url`
   (auto-detected from your Lens checkout, or pass `--lens-repo-url`).
2. **Discovers dependent projects** — scans for sibling `lens.toml` directories
   with SSH git remotes and writes `[[dependent_project]]` entries in
   `lens.toml` so CI knows the full topology.
3. **Discovers dataset repos** — finds non-bundled datasets referenced by your
   project, resolves their git remote URLs, and writes `[[dataset_repo]]`
   entries (so CI can clone them at container boot time).
4. **Installs CI pipeline files** — copies the provider-specific template
   (`.github/workflows/release.yml` or `.gitlab-ci.yml`) and CI scripts into
   your project.

All changes are **uncommitted** — review them with `git diff`, then commit and
push when ready.

> **Already ran `lens release init` before?** Rerunning is safe — it skips
> already-configured entries, re-installs CI files, and reports the current
> state.

#### Example output

```
CI files installed for github:
  ✓ .github/workflows/release.yml

[release] enabled  (repo: git@github.com:my/lens.git)

Dataset repo:  lens-dnd-ext
  url: https://github.com/user/lens-dnd-ext.git
  ref: main  (new)
  ⚠ HTTPS — switch to SSH or confirm it's a public repo (edit lens.toml [[dataset_repo]])

fly.toml:    found

Next steps:
  1. lens release check  (verify configuration)
  2. lens deploy push    (initial build and deploy)
```

---

### 3. Set CI secrets

With the Fly app running and `[release]` configured, the final setup step is to
make sure the CI provider has the secrets it needs.

**Audit what's needed:**

```bash
lens release secrets check --fly
```

This scans your topology (leader, `[[dependent_project]]` s, `[[dataset_repo]]`
s, LLM/image/speech configs) and lists every secret the pipeline needs, whether
it's available in your current shell env, and whether it already exists on the
Fly app.

**Secrets to set in your CI provider:**

| Secret | Required? | Purpose |
|--------|-----------|---------|
| `FLY_API_TOKEN` | Always | Authenticate `flyctl deploy` and `fly secrets set` — generate one with `fly tokens create` or from [fly.io/user/personal_access_tokens](https://fly.io/user/personal_access_tokens) |
| `GIT_REPO_DEPLOY_KEY_<SLUG>` | Per project | SSH deploy key for the leader + each `[[dependent_project]]` repo |
| `DATASET_REPO_DEPLOY_KEY_<NAME>` | Per private `[[dataset_repo]]` | SSH deploy key for a dataset repo that needs private access |
| Any `api_key_env` from `lens.toml` | If provider used | LLM / image / speech API keys |

**Secrets that stay on Fly (never in CI):**

| Secret | Purpose | Set by |
|--------|---------|--------|
| `CADDY_BASIC_AUTH_USER` / `CADDY_BASIC_AUTH_HASH` | Basic Auth for the deployed app | `lens deploy init` |
| `PROJECT_REPO_URL_<SLUG>` | Git remote URL per project | `lens deploy init` |
| AWS env vars | S3 credentials | `lens deploy init` |

If `lens release secrets check --fly` reports "Deployment secrets missing from
Fly app", it means `lens deploy init` was never run (or its secrets were
cleared). Run it from your desktop to set them.

> **Every secret already on Fly can be omitted from your CI env** — the
> pipeline only pushes secrets that are present in the CI environment. Secrets
> already set on Fly are left untouched.

---

## Deploying

### Desktop push

```bash
lens deploy push
```

Optional: `--mode fly` (default, Fly builder), `--mode depot`, or `--mode local`
(build locally with Docker, then push).

Run from the directory containing `fly.toml`, from inside that project, or —
in a multi-project deployment — from its parent directory.

`push` re-syncs all LLM, image, and speech `api_key_env` secrets from your
current shell into the Fly app (then deploys). So you can add a new
`[[image]]` block, export the key locally, and run `lens deploy push` without
re-running `init`.

On first boot, `start.sh` clones each repo onto the volume. On subsequent boots
it fast-forwards from `origin`. The volume is never touched by a redeploy.

### CI release pipeline

After the three setup steps above, every push that contains a Lens version
update triggers the release pipeline automatically:

1. A user clicks **Update** in the Lens UI, which writes `requested_version` +
   `requested_from_commit` into `lens.toml` (uncommitted).
2. Their next **Checkpoint** commits and pushes both fields to the remote.
3. The push triggers the release leader's CI pipeline (`release.sh`), which:
   a. Checks every required secret is present in the CI environment
   b. Verifies the parent-hash match gate (ensures only authorised commits
      trigger a release)
   c. Syncs secrets from CI to Fly (additive — never deletes existing secrets)
   d. Prints build parameters for the target Lens version
   e. Runs `flyctl deploy --build-arg LENS_VERSION=<tag>`
4. The new container boots, clones/fast-forwards all project and dataset repos,
   and the app is live on the new version.

CI **never writes to git** — the check + sync + deploy flow is read-only
(except for `fly secrets set`, which writes to the Fly app's secret store).
Deploy errors are surfaced in CI run logs.

#### Pipeline templates

| File | Purpose |
|------|---------|
| `deploy/ci/release.sh` | Shared shell script: secrets check → check-release → sync → apply → deploy |
| `deploy/ci/release_secrets.py` | Standalone Python (zero deps outside Lens venv): check, sync, apply |
| `deploy/ci/github-release.yml` | GitHub Actions pipeline template (calls `release.sh`) |
| `deploy/ci/gitlab-release.yml` | GitLab CI pipeline template (calls `release.sh`) |

These are installed into your project by `lens release init`. Edit the provider
template to set the correct `--since` commit range for the parent-hash gate.

---

## Managing projects

To add a project to an existing deployment:

```bash
lens deploy add campaign-c --deploy-key ~/.ssh/key_c
lens deploy push
```

To remove one:

```bash
lens deploy remove campaign-b
lens deploy push
```

`add` sets the new project's secrets and updates `fly.toml`. `remove` clears
them. `push` redeploys with the new configuration. Shared provider keys
(`api_key_env` values) are not cleared on remove — they may still be needed by
remaining projects.

When adding a project in CI-release mode, use `lens release add` instead; it handles the Fly secrets plus the leader's `[[dependent_project]]` entry. `lens release remove` does the inverse. Desktop-mode deployments (no `[release]` section) continue to use `lens deploy add/remove`.

Writing a `[[dependent_project]]` entry by hand is not enough: the container derives its project list from the `PROJECT_REPO_URL_<SLUG>` secrets that only `lens release add` sets, so a hand-added entry serves nothing. `init`/`add`/`push` now fail with an explicit error when the leader declares a dependent that is not a deployed slug.

---

## Operations

### Updating Lens (code, datasets, UI)

Pull the latest Lens code locally, then:

```bash
lens deploy push
```

This rebuilds the Docker image. Project repos on the volume are untouched.
External datasets referenced in deployed projects are copied into the image
under `datasets/<name>/` during `push`.

### Updating project content

Push local changes to the Git remote, then use the **Refresh** button in the
web UI (or `POST /refresh` on the API). The server does a `git fetch` +
fast-forward merge.

### Volume

The Fly volume at `/data` persists across restarts, redeploys, and machine
suspend/resume. It is tied to one machine in one region.

**Recovery**: The volume is not replicated. Your Git remotes are the durable
copies. Use `lens checkpoint` (via the web UI) to push work off the server
before doing anything risky. Fly volume snapshots provide additional disaster
recovery (`fly volumes snapshots list`).

### Machine lifecycle

The default config suspends the machine after idle time and resumes it on the
next request (a few seconds of wake latency). To keep it always on, set
`min_machines_running = 1` in `fly.toml` and redeploy.

### SSH into the machine

```bash
fly ssh console --app my-campaign
```

### Logs

```bash
fly logs --app my-campaign
```

### Managing secrets

Fly secrets persist across restarts and redeploys. You can set them directly
without running `lens deploy init` or having env vars in your shell — just
read the file at command time:

```bash
fly secrets set \
  GIT_REPO_DEPLOY_KEY_CAMPAIGN_A="$(cat ~/.ssh/campaign-a-deploy)" \
  --app my-campaign
```

If a `fly.toml` exists in the current directory, `--app` is optional:

```bash
cd projects/
fly secrets set \
  DATASET_REPO_DEPLOY_KEY_LENS_DND="$(cat ~/.ssh/lens-dnd-deploy)"
```

To get a Fly API token for CI setup:

```bash
fly tokens create
```

Or create one with a brief expiry at [fly.io/user/personal_access_tokens](https://fly.io/user/personal_access_tokens).

`lens release secrets check --fly` shows which secrets are already on the Fly
app and which are missing. The machine restarts automatically after any secret
change.

### Changing the password

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'new-password', bcrypt.gensalt()).decode())"
fly secrets set CADDY_BASIC_AUTH_HASH='$2b$12$...' --app my-campaign
```

### Scaling (should not be needed and may incur you cost)

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

### Configuring CI secrets (`lens release secrets`)

```bash
lens release secrets check                       # audit what's needed
lens release secrets check --fly                 # also check Fly app
lens release secrets sync --fly-app my-campaign  # push CI env → Fly
```

See [Tools reference](#tools-reference) for details.

---

## Tools reference

| Command | What it does | When to use |
|---------|-------------|-------------|
| `lens deploy init` | Create Fly app, volume, secrets, `fly.toml` | First-time setup (desktop only) |
| `lens deploy push` | Build and deploy Docker image | Desktop deploy, or initial deploy after setup |
| `lens deploy add` | Add project to an existing deployment | Adding a project |
| `lens deploy remove` | Remove project from a deployment | Removing a project |
| `lens deploy push --mode local` | Build locally with Docker, then deploy | When Fly remote builder is slow |
| `lens release push` | Same as `lens deploy push`, but required when `[release]` is enabled | Release-managed deployments |
| `lens release add` | Adds a project’s secrets and `[[dependent_project]]` entry | Multi-project release deployments |
| `lens release remove` | Removes a project from the release topology | Multi-project release deployments |
| `lens release init` | Enable `[release]`, discover topology, install CI files. `--leader` to designate this project as leader; from a parent deploy dir use `--as-leader <slug>` | After `lens deploy init`, one-time |
| `lens release check` | Show release status (version, CI files, topology) | Verify configuration |
| `lens release apply` | Set `requested_version` + `requested_from_commit` | Trigger a release (also done by UI) |
| `lens release clear` | Cancel a pending release | Undo an accidental apply |
| `lens release secrets check` | Audit required secrets vs CI env (+ `--fly`) | Before setting up CI, after deploys |
| `lens release secrets sync` | Push CI-available secrets to Fly app | CI pipeline only |
| `deploy/ci/release.sh` | CI pipeline driver (check → check-release → sync → apply → deploy) | Called by CI provider template |
| `deploy/ci/release_secrets.py` | Standalone check / sync / apply (zero deps) | CI pipeline (no Lens package available) |

---

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
| `fly.toml` | Generated by `lens deploy init` |

---

## Local deploy (Caddy on your machine)

Run Lens on your own machine and expose it safely via Caddy (HTTPS + Basic
Auth). Lens must only bind to localhost; Caddy is the only public entrypoint.

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

For external access, point `lens.example.com` to your machine's IP and forward
TCP 443 from your router. For DNS-01 certificates or dynamic DNS, use a custom
Caddy build with the appropriate provider module.
