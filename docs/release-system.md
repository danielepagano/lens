# Release system: project-centric cloud deploy & upgrade

Implements GitHub issue **#55 — "Project-centric cloud deploy (not from Lens repo)"**.

Today, deploying and upgrading Lens (`deploy/README.md`) requires a desktop with a
checked-out copy of the Lens tool repo: `lens deploy push` builds the Docker image
from your local clone and pushes it to Fly. There is no way to deploy or upgrade
a project from CI alone, and no way to auto-update either the Lens application or
the external datasets a project depends on.

This document is the **implementation plan**, split into discrete, independently
shippable phases. Each phase should land as its own PR and pass `poe check`. Read
this whole document before starting Phase 1 — later phases depend on decisions
made in earlier ones.

## Non-goals (explicitly out of scope for this plan)

- Replacing or changing the existing desktop `lens deploy` command family. It
  stays exactly as documented in `deploy/README.md`; everything here is additive.
- Deployment stacks other than Fly.io. The apply/deploy step is Fly-specific;
  the version decision engine is stack-agnostic.
- Automatic rollback of a bad release. Out of scope; noted as a follow-up in
  Phase 10.
- **Data migration.** A major Lens version bump still needs to be surfaced
  and human-approved in the app before it's deployed (see decisions #3/#4),
  but this plan assumes project data needs no transformation across major
  versions — approval is a plain "go ahead and deploy this" click, nothing
  more. Actually mutating project data when a future major version requires
  it is spun off to a future feature: **#88**.
- Dataset **code** (Python extensions) version-gating against Lens major
  versions. Per the issue, dataset repos are always auto-updated to their
  latest commit on their tracked ref, no version compatibility system. If a
  dataset ships an extension package, keeping it working across Lens versions
  is the dataset author's problem, not this system's.
- Automatic election or failover of the release leader in a multi-project
  Fly deployment (decision #8). Designating (and re-designating, if the
  leader project is ever removed) `[release] app_leader = true` is a manual,
  one-time operator action, not something the system infers.

## Phase difficulty at a glance

For picking which model/reviewer effort to assign per phase. Rated on how much
novel design judgment, cross-cutting/moving parts, and hard-to-test surface
area is involved — not raw line count.

| Phase | Title | Difficulty | Why |
|-------|-------|------------|-----|
| 1 | Config schema & validation | **Low** | Pure parsing/validation, closely mirrors existing `[[llm]]`-style code already in the repo. |
| 2 | Version resolution core | **Medium** | New subprocess/git-plumbing + semver edge cases, but fully unit-testable against local fixture repos, no network. |
| 3 | ~~Migration framework~~ — spun off to **#88** | — | No data migration in this plan; see non-goals. |
| 4 | Release decision engine (`check`/`apply`) | **Medium** | Branching state-machine paths (policy vs. requested version vs. pending major-bump approval vs. downgrade rejection) that all have to be exactly right; JSON contract consumed by two different CI systems later. |
| 5 | App-side server routes | **Medium** | Mostly plumbing over the existing `Storage` commit/push pattern already proven by `checkpoint`. |
| 6 | UI: Release panel | **Medium** | Standard Svelte feature work following established feature-folder conventions; a simple approve/reject banner, no diff review. |
| 7 | Dataset repo runtime sync | **High** | Spans bash (`start.sh`), Python (`resolve_dataset_path`, `refresh`), and deploy secret plumbing across both the desktop and cloud paths — many small moving parts that must agree. |
| 8 | Bake `LENS_VERSION` + desktop version computation | **Medium** | Dockerfile change is trivial; the local tag/short-hash computation (per the new decision #7) is a small but fiddly bit of git plumbing with a few edge cases (no tags, detached HEAD, dirty tree). |
| 9 | CI reference pipelines (GitHub + GitLab) | **Very High** | Two separate CI systems, real Fly deploys, and secrets/host-specific glue that this repo's own test suite can't fully exercise — most of the risk here is only discoverable by running it for real. |
| 10 | End-to-end validation & docs polish | **High** | Large integration test tying every prior phase together correctly; not novel design, but any gap in earlier phases surfaces here first. |

## Key design decisions

These resolve ambiguity in the issue text; call them out explicitly so
reviewers can push back before implementation starts.

1. **State lives in `lens.toml`, not a separate file.** A new `[release]`
   table and `[[dataset_repo]]` array. Both the deployed app and headless CI
   read/write it through the existing `Storage` commit/push mechanism (the
   same one `lens checkpoint` uses) — git is the only channel between the app
   and CI, there is no shared runtime state.

2. **Minimize persisted version state — prefer live checks.** Only facts that
   must survive across independent CI runs / app restarts are persisted:
   - user intent (`auto_update` policy, `requested_version`)
   - in-flight major-bump approval handshake state (`gated_update_pending`,
     `gated_update_target_version`, `gated_update_approved`)

   > Phase 1 (already shipped) persisted `data_major_version` and
   > `migration_pending`/`migration_target_version`/`migration_commit`
   > instead — fields designed for the data-migration handshake now spun off
   > to **#88**. They're dead weight under this trimmed plan. Phase 4 below
   > replaces them with the `gated_update_*` fields described here as part of
   > implementing the decision engine; there's no standalone cleanup phase
   > for this, since Phase 4 hasn't shipped yet.

   Everything else is computed live and **never committed**:
   - "Currently installed (tag)" — read from the running container's own
     `LENS_VERSION` environment variable, baked in at Docker build time from
     the git tag CI checked out. This is what makes "Perform releases
     (tag-based, no commit needed)" true for minor/patch bumps: applying a
     minor/patch release is *only* "build image from tag X, deploy it" —
     nothing to write back to the project repo.
   - "Latest available" — computed on demand via `git ls-remote --tags` against
     the tracked Lens repo URL (no auth needed for public repos; same SSH
     deploy-key mechanism as project repos for private forks). The CLI
     (`lens release check`) and the server route both call the same core
     function; the server may cache it in-process for a short TTL to avoid
     hammering the remote on every page load, but never writes it to git.

 3. **Major-bump approval happens in the deployed app UI, not via a PR — and
    involves no data migration.** Per the non-goals above, this plan assumes
    project data needs no changes across a Lens major version, so there's
    nothing to run and nothing to diff. When `check` finds a target whose
    major is greater than the currently installed major, CI commits
    `gated_update_pending = true` and `gated_update_target_version = <tag>`
    directly to the tracked branch (not a side branch) — a pure metadata
    write, no project files touched. The Lens app shows a banner naming the
    target version (linking out to the Lens repo's release notes for context)
    with an Approve/Reject action. Approving commits
    `gated_update_approved = true` (pushed via the same Storage/checkpoint
    pattern); that push is what triggers the next CI run to actually build
    and deploy the tag. This works identically for GitHub- and GitLab-hosted
    project repos, since it never touches a host-specific PR API.

    **While a major bump is pending, minor/patch updates within the current
    major version are NOT blocked.** The `check` command still runs
    `_select_target_tag` and applies a same‑major target immediately —
    only a cross‑major target triggers the `await_approval` gate. See
    Decision #4 and the Phase 4 check flow for the combined rules.

    Rejecting clears the `gated_update_pending` / `gated_update_target_version`
    / `gated_update_approved` fields and pushes the change. The next `check`
    run will re‑evaluate the target from scratch — if the same tag is still
    the best candidate (per policy or `requested_version`), it will be offered
    again. This is intentional: rejection is a "not now," not a "never." To
    stop being asked about a particular tag, change the `auto_update` policy
    or remove the `requested_version` that selected it.

 4. **Any major bump always requires the approval handshake**, regardless of
    whether the target was reached via `auto_update = "major"` or an explicit
    `requested_version`. Policy only controls whether CI acts autonomously for
    **minor/patch** bumps and which version it aims for; it never skips human
    review for a major bump — even though, under this plan, that review has
    nothing to inspect but the version number itself.

    **Critically, a pending major bump does not block minor/patch updates
    within the current major.** The `check` command evaluates the target
    through `_select_target_tag` (which respects `auto_update` and
    `requested_version`) before checking the major boundary. If the selected
    target shares the installed major, it proceeds as `apply` — only a target
    whose major exceeds the installed major triggers the gated approval path.
    This means a project on `auto_update = "minor"` will keep receiving the
    latest v1.x patches even while approval for v2.0.0 awaits a human click.

5. **Dataset repos are tracked but never version-gated.** They're cloned onto
   the same Fly volume as project repos (extending the existing `start.sh`
   clone/fast-forward logic), not baked into the Docker image. "Auto-update"
   for a dataset is exactly the existing content **Refresh** mechanism
   (`git fetch` + fast-forward), extended to also run against each
   `[[dataset_repo]]` clone. No image rebuild, no CI build required in the
   common case — a CI cron (or the app itself on a timer) just calls the
   refresh endpoint. This is a large scope reduction versus the Lens-version
   engine and reuses infrastructure that already exists.

6. **CI mechanics are provider-neutral; only the trigger/secrets glue is
   provider-specific.** All decision logic lives in new `lens release *` CLI
   subcommands (plain Python, testable without any CI runner). GitHub Actions
   and GitLab CI each get a thin, mostly-declarative pipeline file that only
   handles triggers, secrets, and calling those CLI commands + `flyctl`. This
   matches the user's own project layout (Lens tool repo on GitHub, project
   repos on GitLab) and forces the core to stay host-agnostic.

7. **Desktop `lens deploy push` computes `LENS_VERSION` from local tags, not
   `git describe`.** It reads the Lens repo checkout's own tags (the same
   semver parsing as Phase 2, applied locally instead of over `ls-remote`),
   finds the latest release tag, and:
   - if `HEAD` **is** that tag's commit → `LENS_VERSION = <tag>` (e.g.
     `v1.4.2`) — a clean release build.
   - if `HEAD` is **not** that tag's commit (you're ahead of the last tag,
     mid-development) → `LENS_VERSION = <tag>+<short-hash>` (e.g.
     `v1.4.2+a1b2c3d`) — using `+` (semver build metadata) rather than `-`
     since this isn't a formal pre-release channel, just "last known tag,
     plus this exact commit." This is informational only — the release
     decision engine (Phase 4) never parses or compares this value, it only
     reads remote tags. Practically, this is what lets you `lens deploy push`
     a not-yet-tagged commit straight from your desktop checkout for manual
     testing, while still being able to tell at a glance which release
     lineage it's based on.
   - no tags at all in the checkout → `LENS_VERSION = 0.0.0+<short-hash>`.

8. **A multi-project Fly app designates exactly one release leader; there is
   no cross-project reconciliation.** `deploy/README.md` already documents a
   parent-of-projects `fly.toml` topology — one Fly app, one deployed Lens
   binary, several project repos underneath it, possibly on different Git
   hosts entirely. But there is only **one** `LENS_VERSION` for that whole
   app, so the `[release]` state (decision #1) can't independently live in
   every served project's own `lens.toml` — two sibling projects' CI
   pipelines could pick different targets and race to `fly deploy` the same
   app, or show conflicting approval banners for a version that only one of
   them actually controls. Rather than inventing a new app-level config
   file/repo (which would need its own git remote and CI wiring, on top of
   whatever host each project already uses), exactly one served project is
   flagged `[release] app_leader = true`; its `lens.toml` is the single
   source of truth for that Fly app, and only its CI pipeline is wired up to
   run `lens release apply` + `flyctl deploy` (Phase 9). Server routes
   (Phase 5) resolve to the leader's config regardless of which project's
   slug was in the request URL, so every served project's UI shows/controls
   the identical shared state — there's no "wrong project" error. This is a
   manual, one-time designation: there's no automatic election or failover
   if the leader project is ever removed from the deployment (`lens deploy
   remove`) — the operator must re-flag a new leader by hand. Single-project
   apps are entirely unaffected; `app_leader` is ignored there since the
   lone served project is trivially the leader.

   `lens deploy init` / `add` / `push` validate this topology up front (the
   only place that already resolves every sibling's `lens.toml` locally —
   see `_validate_release_topology` in `lens/core/commands/deploy.py`):
   at most one project may set `app_leader = true`, no non-leader project
   may enable `[release]` at all, and — since it's the same kind of
   cross-project consistency problem — `[[dataset_repo]]` entries sharing a
   `name` across sibling projects must agree on `git_url`/`ref` (otherwise
   they'd race for the same clone on the shared Fly volume; see Phase 7).
   `lens release check`/`apply` also work when run **from the parent
   deploy directory itself** (not just from inside a project) — they detect
   the `fly.toml`-only, no-`lens.toml` directory shape, run the same
   topology validation, and resolve to the leader's project root, instead of
   failing with a generic "not inside a git repository" error.

## Config schema (target shape)

```toml
# lens.toml

[release]
enabled            = true
lens_repo_url       = "https://github.com/danielepagano/lens.git"  # default; override for a fork
auto_update         = "minor"   # "off" | "minor" | "major"
requested_version   = ""        # e.g. "v2.1.0"; explicit override, cleared once fulfilled
gated_update_pending        = false  # set by CI when a major bump is waiting on human approval
gated_update_target_version = ""
gated_update_approved       = false
app_leader                  = false  # required (and must be true on exactly one project) when
                                      # this Fly app serves >1 project — see decision #8

[[dataset_repo]]
name    = "lens-dnd"
git_url = "git@gitlab.com:org/lens-dnd.git"
ref     = "main"
```

`installed_version` and `latest_available_version` are **not** stored here —
see decision #2.

> Phase 1 shipped with `data_major_version`/`migration_pending`/
> `migration_target_version`/`migration_commit` instead of the
> `gated_update_*` fields shown above — see the note under decision #2.

## Architecture at a glance

```
Deployed Lens app (Fly)                    Project repo (git)                CI (GitHub Actions / GitLab CI)
------------------------                   ------------------                --------------------------------
reads LENS_VERSION env  <---------------- (baked at image build) <---------- checks out Lens repo at target tag,
  "currently installed"                                                       builds image, fly deploy

reads/writes [release]  <---- commit+push ---->  lens.toml [release]  <---- commit+push ---- lens release check/apply
  via Storage (like checkpoint)                                                                (reads + writes same table)

live git ls-remote  ---------------------> Lens repo tags (GitHub, any fork)   <---- same ls-remote, used by `check`

Refresh action  -----------------------> project + [[dataset_repo]] clones on volume  <---- CI cron just calls /refresh
```

This diagram is the single-project case (one Fly app, one project repo). For
a Fly app serving several projects (decision #8), "Project repo" / "CI" on
the right only exist for the one project flagged `app_leader = true` —
siblings have no `[release]` state and no release-triggering CI at all; the
deployed app's server routes still resolve to the leader's `lens.toml`
regardless of which served project's UI made the request.

---

## Phase 1 — Config schema & validation [COMPLETED]

**Difficulty: Low**

**Goal:** `lens.toml` can express `[release]` and `[[dataset_repo]]`; nothing
acts on it yet.

- `lens/core/release/config.py` (new): `ReleaseConfig` and `DatasetRepoConfig`
  dataclasses + a loader/parser off the already-parsed `lens.toml` dict
  (mirror the style of existing `[[llm]]`/`[[image]]` parsing in
  `lens/core/project.py` / `lens/core/commands/deploy.py`).
- Defaults: `[release]` absent → release system disabled entirely (all new
  CLI commands and routes no-op with a clear "release system not enabled"
  message); `auto_update` defaults to `"off"`.
- Validate in `lens check` (`lens/core/commands/check.py`): `auto_update` is
  one of the three allowed values; `lens_repo_url` is a valid SSH/HTTPS git
  URL (reuse `parse_git_ssh_remote` where SSH); `data_major_version` is a
  non-negative int (`0` is valid — e.g. a project tracking Lens's pre-1.0
  major line); each `[[dataset_repo]]` has `name` (matches an entry in
  `[project].datasets`, or warn if not — a declared repo that nothing
  references is likely a mistake), a valid `git_url`, and `ref` defaulting to
  `main`.
- Add release medatada to `lens stats` for CLI visibility (API comes later)
- Unit tests only (`lens/core/test/`), no network, no CI, no server changes.

**Docs:** add `[release]` / `[[dataset_repo]]` reference tables to
`docs/configuration.md` (schema + field meanings only; operational docs come
in later phases).

> **Note (post-trim):** this phase shipped before the data-migration engine
> was spun off to #88, so it validates `data_major_version` and the
> `migration_*` fields rather than the `gated_update_*` fields now described
> in the [config schema](#config-schema-target-shape) above. Phase 4 below
> is where those fields get replaced for real.

---

## Phase 2 — Version resolution core (live checks) [COMPLETED]

**Difficulty: Medium**

**Goal:** given a `ReleaseConfig`, compute "latest available" and expose
"currently installed" — no mutation, no CI yet.

- `lens/core/release/version.py`:
  - Semver tag parsing/comparison for `vMAJOR.MINOR.PATCH` tags (reject/ignore
    non-matching tags).
  - `list_remote_tags(git_url) -> list[SemverTag]` via `git ls-remote --tags
    <url>` (subprocess, same pattern as `Storage`'s git calls). Support SSH
    URLs with a deploy key the same way project repos do (accept an optional
    `ssh_key_path`/`GIT_SSH_COMMAND` override for private forks).
  - `latest_within_major(tags, major) -> SemverTag | None` and
    `latest_overall(tags) -> SemverTag | None`.
  - `installed_version() -> str | None` reads `os.environ["LENS_VERSION"]`
    (unset when running from a desktop checkout / not yet baked — return
    `None`, callers must handle it).
- `lens/core/release/status.py`: `compute_release_status(project_root) ->
  ReleaseStatus` combining config + live tag list + installed version +
  pending-approval fields, into one struct the CLI and the server route will
  both consume in later phases. (Ships today with the pre-trim
  `migration_pending`/`migration_target_version`/`migration_commit` fields —
  see the note under Phase 1.)
- As a sanity check, expose this data in CLI `lens stats` (under Release section)
- Tests: no real network — spin up a local bare git repo with tags in a
  tempdir (`git init --bare`, `git tag`, `git push`) and point
  `list_remote_tags` at its `file://` path. Cover: no tags, only-prerelease
  tags (ignored), mixed majors, private-URL-with-key plumbing (mock the
  subprocess call).

---

## Phase 3 — Migration framework [SPUN OFF — see #88]

Actually running a script to transform project data across a Lens major
version — and the diff/revert UX around approving that — is out of scope for
this plan. See the non-goals section above and **#88** for the full former
scope of this phase (migration authoring contract, `migrate.py` chain
resolver/runner, `lens release migrate`, and the diff-review parts of
Phases 4–6 below).

Under this trimmed plan, a major version bump needs **only** human approval
before it's deployed (Phase 4), with no data mutation step in between.

---

## Phase 4 — Release decision engine (`check` / `apply`) [COMPLETED]

**Difficulty: Medium**

**Goal:** the CLI surface CI actually calls, with a JSON contract for
branching in a pipeline.

- This phase replaces Phase 1's `data_major_version`/`migration_*` fields
  with `gated_update_pending`/`gated_update_target_version`/
  `gated_update_approved` (see decision #2's note and the config schema
  above) — update `ReleaseConfig`/`ReleaseStatus`, validation, and the
  `lens stats` display accordingly as part of this phase's work, not as a
  separate cleanup step.
 - `lens release check` — reads config + live status (Phase 2), and:
   1. If `gated_update_pending` and `gated_update_approved`: JSON
      `{"action": "apply", "target": "<approved tag>"}` — the approved major
      bump is ready to build and deploy.
   2. Pick a target tag per decision #4 above (explicit `requested_version`
      wins if set and newer than installed; otherwise `auto_update` policy
      ceiling; `off` → no target).
      - Reject (non-zero exit, clear error) a `requested_version` older than
        the currently installed tag or an unparseable tag — never silently
        downgrade.
   3. No target and no pending gated update: JSON `{"action": "none"}`.
   4. No target but a pending gated update exists (no minor/patch available
      within the current major, but a major bump is still awaiting approval):
      JSON `{"action": "await_approval", "target": "<pending tag>"}`.
   5. Target shares the installed major (minor/patch): JSON
      `{"action": "apply", "target": "<tag>"}` — no approval needed, straight
      to build+deploy. **This fires even if a cross-major gated update is
      also pending** (Decision #4).
   6. Target major > installed major: commits
      `gated_update_pending = true`, `gated_update_target_version = <tag>`
      (pure metadata write, no project files touched — decision #3), JSON
      `{"action": "await_approval", "target": "<tag>"}`. If already pending,
      the metadata write is a no-op. CI stops here; the app surfaces the
      approval banner (Phase 6).
- `lens release apply --to <tag>` — prints the build parameters CI needs
  (Lens repo URL + tag to check out) as JSON. **Makes no commit** in the
  common case (decision #2) — matches "tag-based, no commit needed"
  literally.
  - Exception: if this `apply` is *fulfilling* a previously approved major
    bump (i.e. `gated_update_approved == true` and
    `gated_update_target_version == tag`), it also clears
    `gated_update_pending` / `gated_update_target_version` /
    `gated_update_approved` in one commit+push. This is the only case
    `apply` commits.
- All output is JSON on stdout, human summary on stderr, so CI YAML can do
  `RESULT=$(lens release check --json)` and branch on `.action`.
- Tests: integration-style, using the Phase 2 fixtures; cover all four
  branches above plus the downgrade-rejection case.
- **Multi-project deploy support (decision #8):** adds `app_leader` to
  `ReleaseConfig`/`ReleaseStatus` alongside the `gated_update_*` fields above,
  and:
  - `lens/core/release/config.py`: `validate_deploy_topology(project_configs)`
    — given `[(slug, ReleaseConfig, [DatasetRepoConfig]), ...]` for every
    project sharing one Fly app, raises if more than one sets
    `app_leader = true`, if any non-leader project has `[release] enabled =
    true`, or if sibling projects declare a `[[dataset_repo]]` with the same
    `name` but a different `git_url`/`ref`. No-op for a single project.
  - `lens/core/commands/deploy.py`: `_validate_release_topology` calls the
    above from `init_deploy`, `add_project`, and `push_deploy` — the only
    places that already resolve every sibling's `lens.toml` locally, so
    misconfiguration is caught at setup/deploy time rather than at CI runtime.
  - `lens/core/commands/release.py`: `resolve_release_project_root(cwd)` —
    used by the `lens release check`/`apply` CLI instead of a plain
    `ProjectSession.from_cwd()`. If `cwd` (or an ancestor) has its own
    `lens.toml`, behaves exactly as before (works from inside any single
    project, leader or not). Otherwise, if `cwd` has a `fly.toml` (the
    parent-of-projects topology, no sibling `lens.toml`), it reads
    `LENS_PROJECT_SLUGS`, builds every sibling's config, runs
    `validate_deploy_topology`, and resolves to the leader's project root —
    so `lens release check`/`apply` work when run from the deploy directory
    itself instead of failing with "not inside a git repository". Raises a
    clear error if no project sets `app_leader = true`.
  - Tests: unit tests for `validate_deploy_topology` (leader-uniqueness,
    non-leader-enabled, dataset_repo conflict cases) and for
    `resolve_release_project_root` against a fixture multi-project directory
    (bare-git siblings, mirroring the Phase 2/4 fixture style).

---

## Phase 5 — App-side server routes [COMPLETED]

**Difficulty: Medium**

**Goal:** the deployed app can read status, mutate policy, and approve a
pending major-version bump; no UI yet (routes + tests only).

- `lens/server/routes/release.py`:
  - `GET /{slug}/release/status` → `compute_release_status` (Phase 2) as JSON:
    enabled, installed (from `LENS_VERSION` env, `None` if unset), latest
    available (live check, short in-process TTL cache — e.g. 5 minutes),
    auto_update policy, requested_version, and gated-update pending info
    (`gated_update_pending`, `gated_update_target_version`). No diff to
    surface — nothing but the metadata flags changed (decision #3).
  - `POST /{slug}/release/policy` `{auto_update?, requested_version?}` →
    updates `[release]` in `lens.toml` and commits+pushes via `Storage`
    (mirrors `execute_checkpoint`).
  - `POST /{slug}/release/gated-update/approve` → sets
    `gated_update_approved = true`, commits+pushes.

  - All routes 404 with a clear message when `[release]` is absent/disabled
    (matches Phase 1's "no-op" default).
  - **Multi-project deploy (decision #8):** every route resolves to the
    release *leader's* `lens.toml` regardless of which project's `{slug}`
    is in the URL — add a core helper (e.g.
    `resolve_release_leader_slug(project_root)`) that reads
    `LENS_PROJECT_SLUGS` and, when it names more than one project, scans
    each sibling clone already present at `LENS_PROJECT_DIR/<slug>/` for
    `app_leader = true`; falls back to the current project when there's
    only one slug. Both reads and writes (policy, approve, reject) go
    through this resolution, so every served project's UI transparently
    shows/controls the same shared state — there is no separate "you're
    not the leader" error path to build.
- No business logic in routes — all of the above lives in
  `lens/core/commands/release.py`, routes just validate + call + map
  exceptions to HTTP errors (per the server rules in `CLAUDE.md`).
- Tests: `lens/server/test/` route tests using the existing test-client
  fixtures; a fake bare-git-remote fixture for the live tag check (Phase 2).

---

## Phase 6 — UI: Release panel [COMPLETED]

**Difficulty: Medium**

**Goal:** visible, usable controls in the Svelte app.

- New feature folder `lens/server/ui/src/features/release/` (mirrors existing
  feature folder conventions — check `stats`/`projects` features for the
  pattern to copy).
- `services/releaseService.ts` — all fetch calls (per the "network logic only
  in services/" rule).
- `stores/releaseStore.ts` — status, loading/error state.
- Components: a settings-style panel showing installed/latest/policy
  controls (radio or select for off/minor/major, a text input + "Request
  version" button), and — when `gated_update_pending` — a prominent banner
  naming the target version (with a link out to the Lens repo's release
  notes/tags page for context) and Approve/Reject buttons. No diff view —
  there's nothing to diff (decision #3).
- Wire into the existing settings/layout surface (find where `stats` or
  similar project-level info is already surfaced — likely a settings route or
  sidebar section; follow the existing `MainLayout.svelte` structure, do not
  redefine layout).
- **Multi-project deploy (decision #8):** no special-casing needed beyond a
  cosmetic note — when `stats`/`release/status` reports more than one slug
  under `LENS_PROJECT_SLUGS`, show a small "this Lens version applies to all
  N projects on this deployment" indicator, since an operator viewing any
  one project's panel is also affecting its siblings (Phase 5 already makes
  the underlying state shared/transparent).
- Tests: Vitest component/store tests (`poe test-ui`); one Playwright e2e
  happy-path (policy change persists; gated-update approve banner appears and
  clears) added to `e2e/tests/test_browser.py` or a new
  `test_release_browser.py`, following the regression-fixture pattern in
  `e2e/fixtures/README.md`.

---

## Phase 7 — Dataset repo runtime sync

**Difficulty: High**

**Goal:** `[[dataset_repo]]` entries are cloned onto the Fly volume and kept
up to date via the existing refresh mechanism; no CI involvement required.

- **Already shipped in Phase 4** (decision #8): the static consistency check
  that sibling projects sharing a Fly app must agree on `git_url`/`ref` for
  any `[[dataset_repo]]` `name` they have in common
  (`validate_deploy_topology` in `lens/core/release/config.py`, enforced by
  `lens deploy init`/`add`/`push`). This phase is the runtime counterpart —
  it doesn't need to re-validate agreement, just clone/refresh by name.
- Extend `deploy/start.sh`: after cloning/fast-forwarding each project repo,
  do the same for each `[[dataset_repo]]` declared across all served
  projects, into `REPOS_DIR/_datasets/<name>` (one shared clone per dataset
  name, since datasets are shared/reference material — de-dupe by name the
  same way `push_deploy`'s `_resolve_external_datasets` already de-dupes for
  the desktop flow). Reuse the same per-repo deploy-key SSH setup pattern
  already in `start.sh` for project repos (`DATASET_REPO_DEPLOY_KEY_<NAME>`
  secret, keyed by uppercased name).
- Extend `lens/core/project.py` `resolve_dataset_path` with a new resolution
  tier, gated behind `LENS_CLOUD_DEPLOYED=1`: check
  `${LENS_PROJECT_DIR}/_datasets/<name>` before falling back to
  sibling-folder resolution (which won't exist in cloud anyway, but keep
  order well-defined and tested).
- Extend `lens/core/commands/refresh.py` (`execute_refresh`) to also
  fetch+fast-forward every `[[dataset_repo]]` clone referenced by the active
  project (best-effort per repo — one dataset failing to update shouldn't
  block project content refresh; surface a warning per repo instead).
- Deploy plumbing: `lens deploy init` / `add` / `push` (desktop flow) gain the
  ability to also set `DATASET_REPO_DEPLOY_KEY_<NAME>` secrets when a
  project's `[[dataset_repo]]` entries are private — additive flags only, no
  change to existing desktop behavior for projects without `[[dataset_repo]]`.
- Tests: extend `e2e/testing/project.py` / a new e2e test that boots
  `FakeLLMServer` + a local bare dataset repo, verifies `resolve_dataset_path`
  picks up the cloud clone, and that `/refresh` fast-forwards it after a new
  commit is pushed to the fake dataset remote.

---

## Phase 8 — Bake `LENS_VERSION` into the runtime image

**Difficulty: Medium**

**Goal:** the running container can self-report exactly which Lens tag it was
built from, with zero git dependency at runtime.

- `deploy/Dockerfile`: add `ARG LENS_VERSION=dev` and `ENV LENS_VERSION=${LENS_VERSION}`
  in the runtime stage.
- Desktop `lens deploy push` (`lens/core/commands/deploy.py` `_fly_deploy`):
  pass `--build-arg LENS_VERSION=$(git -C <lens repo root> describe --tags
  --always)` so the existing desktop flow also gets accurate self-reporting
  (small, additive change — does not alter desktop UX or CLI surface, just
  fixes a previously-unset env var to `dev`/untagged today).
  This is the one small touch to the existing deploy code the plan requires;
  confirm with the user before implementing since they asked to keep desktop
  deploy unchanged — it's additive/non-breaking but touches that file.
- New CI build path (used by Phase 9): passes `--build-arg
  LENS_VERSION=<target tag>` where `<target tag>` came from
  `lens release apply`'s JSON output.
- Tests: a unit test asserting the Dockerfile contains the ARG/ENV lines
  (guards against accidental removal); the server route from Phase 5 gets a
  test that `installed` is `None` when the env var is unset and reflects it
  when set.

---

## Phase 9 — CI reference pipelines (GitHub Actions + GitLab CI)

**Difficulty: Very High**

**Goal:** two ready-to-copy pipeline templates, both thin wrappers over the
Phase 4 CLI commands.

- `deploy/ci/github-release.yml` (template to copy into a project repo's
  `.github/workflows/`): triggers on push to main + a schedule (e.g. hourly).
  Steps: checkout project repo, install `lens` (pinned to whatever tag/commit
  the project is currently tracking — bootstrap problem: the *runner*
  installing `lens` needs a working Lens install to even run `lens release
  check`; install from the currently-installed tag or `main` — call this out
  as an explicit bootstrap rule in the doc), run `lens release check --json`,
  branch on `.action`:
  - `apply`: checkout Lens repo at target tag into a build context, `flyctl
    deploy` with `--build-arg LENS_VERSION=<tag>` (needs `FLY_API_TOKEN`
    secret). This covers both minor/patch bumps and a major bump that was
    already approved in-app.
  - `none`/`await_approval`: no-op (a pending major bump waits for approval
    in the app; nothing for CI to do until the next scheduled run after
    someone clicks Approve).
  Also, on a separate/lighter schedule, `curl -X POST
  https://<app>/<slug>/refresh` (or whatever auth the Caddy layer requires) to
  drive dataset auto-update per decision #5 — document that this needs
  network access from the CI runner to the deployed app (usually fine; note
  the Basic Auth credential must be a CI secret).
- `deploy/ci/gitlab-release.yml` (template to copy into a project repo's
  `.gitlab-ci.yml`): identical steps/stages, GitLab CI syntax
  (`rules`/`schedule` pipelines instead of `on:`).
- `deploy/README.md`: new "CI-driven deploy (no desktop)" section describing
  prerequisites (which secrets go where, on GitHub vs GitLab), how this
  relates to the existing desktop flow (either/or, not both against the same
  Fly app), and a link to this design doc.
- **Multi-project deploy (decision #8):** only the release *leader*
  project's repo gets this pipeline wired up to actually run `lens release
  apply` + `flyctl deploy` for the shared Fly app. Sibling project repos, if
  they have CI at all, only trigger their own content `/refresh` — never the
  Lens-version pipeline; document this explicitly as a setup instruction
  (which repo gets which template) rather than something the pipeline
  itself has to detect. This works even when siblings live on entirely
  different hosts than the leader, because the leader's CI never needs to
  know about them at all: it just checks out Lens at a tag and deploys the
  shared app; datasets are unioned at the runtime-volume layer (Phase 7),
  not baked into the image at build time, so no cross-repo coordination is
  needed at build time either.
- Tests: these are YAML templates, not Python — validate with a lint
  (`actionlint` for the GitHub template if available, `gitlab-ci` linter via
  their API is out of reach in this repo's test suite) or, at minimum, keep
  them out of `poe check`'s scope and cover the underlying CLI commands they
  call with the Phase 4 tests instead. Add one e2e test that shells out the
  exact command sequence a pipeline would run (not the YAML itself) against a
  fixture project + fake upstream repo, to catch drift between the docs and
  reality.

---

## Phase 10 — End-to-end validation & docs polish

**Difficulty: High**

**Goal:** everything wired together, documented, and exercised as a whole.

- One full e2e test (`e2e/tests/test_release_regression.py` or similar):
  fake upstream Lens repo (bare git repo with `v1.0.0`, `v1.1.0`, `v2.0.0`
  tags), fake project repo, walks through: check → apply (minor) → check →
  await_approval (major) → app-side approve (via the Phase 5 routes) → check
  → apply (major, commits + clears the pending fields). Also a fake dataset
  repo exercising Phase 7's refresh path.
- Update `CLAUDE.md` doc map with a row pointing to this file (or fold the
  finished design into `docs/configuration.md` / `deploy/README.md` and
  retire this file — decide at Phase 10 time based on how large the final
  reference docs get).
- Follow-ups to file as separate issues, not part of this plan: automatic
  rollback of a bad deploy; non-Fly deployment stacks; dataset extension code
  version-gating; **data migration across major versions (#88)**.
