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
  the version/migration decision engine is stack-agnostic.
- Automatic rollback of a bad release or migration. Out of scope; noted as a
  follow-up in Phase 10.
- Dataset **code** (Python extensions) version-gating against Lens major
  versions. Per the issue, dataset repos are always auto-updated to their
  latest commit on their tracked ref, no version compatibility system. If a
  dataset ships an extension package, keeping it working across Lens versions
  is the dataset author's problem, not this system's.

## Phase difficulty at a glance

For picking which model/reviewer effort to assign per phase. Rated on how much
novel design judgment, cross-cutting/moving parts, and hard-to-test surface
area is involved — not raw line count.

| Phase | Title | Difficulty | Why |
|-------|-------|------------|-----|
| 1 | Config schema & validation | **Low** | Pure parsing/validation, closely mirrors existing `[[llm]]`-style code already in the repo. |
| 2 | Version resolution core | **Medium** | New subprocess/git-plumbing + semver edge cases, but fully unit-testable against local fixture repos, no network. |
| 3 | Migration framework | **High** | Dynamic module loading/chaining across major versions, must be safely re-runnable, and mistakes here corrupt real project data. |
| 4 | Release decision engine (`check`/`apply`) | **High** | Several branching state-machine paths (policy vs. requested version vs. pending migration vs. downgrade rejection) that all have to be exactly right; JSON contract consumed by two different CI systems later. |
| 5 | App-side server routes | **Medium** | Mostly plumbing over the existing `Storage` commit/push pattern already proven by `checkpoint`; the migration-reject revert path is the trickiest bit. |
| 6 | UI: Release panel | **Medium** | Standard Svelte feature work following established feature-folder conventions; migration diff/approval UX needs some care. |
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
   - the one fact that can't be recomputed: `data_major_version` (the major
     version the project's *data* is currently compatible with — set only
     when a migration is applied)
   - in-flight migration handshake state (`migration_pending`, `_target_version`,
     `_commit`)

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

3. **Migration approval happens in the deployed app UI, not via a PR.** CI runs
   the migration script and commits the result directly to the tracked branch
   (not a side branch), setting `migration_pending = true` in the same commit.
   The Lens app shows a banner with the diff and an Approve/Reject action.
   Approving commits `migration_approved = true` (pushed via the same
   Storage/checkpoint pattern); that push is what triggers the next CI run to
   actually deploy. This works identically for GitHub- and GitLab-hosted
   project repos, since it never touches a host-specific PR API.

4. **Any major bump always requires the migration+approval handshake**,
   regardless of whether the target was reached via `auto_update = "major"` or
   an explicit `requested_version`. Policy only controls whether CI acts
   autonomously for **minor/patch** bumps and which version it aims for; it
   never skips human review for a major bump.

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

## Config schema (target shape)

```toml
# lens.toml

[release]
enabled            = true
lens_repo_url       = "https://github.com/danielepagano/lens.git"  # default; override for a fork
auto_update         = "minor"   # "off" | "minor" | "major"
requested_version   = ""        # e.g. "v2.1.0"; explicit override, cleared once fulfilled
data_major_version  = 1         # bumped only when a migration is applied
migration_pending          = false
migration_target_version   = ""
migration_commit           = ""

[[dataset_repo]]
name    = "lens-dnd"
git_url = "git@gitlab.com:org/lens-dnd.git"
ref     = "main"
```

`installed_version` and `latest_available_version` are **not** stored here —
see decision #2.

## Architecture at a glance

```
Deployed Lens app (Fly)                    Project repo (git)                CI (GitHub Actions / GitLab CI)
------------------------                   ------------------                --------------------------------
reads LENS_VERSION env  <---------------- (baked at image build) <---------- checks out Lens repo at target tag,
  "currently installed"                                                       builds image, fly deploy

reads/writes [release]  <---- commit+push ---->  lens.toml [release]  <---- commit+push ---- lens release check/migrate/apply
  via Storage (like checkpoint)                                                                (reads + writes same table)

live git ls-remote  ---------------------> Lens repo tags (GitHub, any fork)   <---- same ls-remote, used by `check`

Refresh action  -----------------------> project + [[dataset_repo]] clones on volume  <---- CI cron just calls /refresh
```

---

## Phase 1 — Config schema & validation

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
  positive int; each `[[dataset_repo]]` has `name` (matches an entry in
  `[project].datasets`, or warn if not — a declared repo that nothing
  references is likely a mistake), a valid `git_url`, and `ref` defaulting to
  `main`.
- Add release medatada to `lens stats` for CLI visibility (API comes later)
- Unit tests only (`lens/core/test/`), no network, no CI, no server changes.

**Docs:** add `[release]` / `[[dataset_repo]]` reference tables to
`docs/configuration.md` (schema + field meanings only; operational docs come
in later phases).

---

## Phase 2 — Version resolution core (live checks)

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
  migration-pending fields, into one struct the CLI and the server route will
  both consume in later phases.
- Tests: no real network — spin up a local bare git repo with tags in a
  tempdir (`git init --bare`, `git tag`, `git push`) and point
  `list_remote_tags` at its `file://` path. Cover: no tags, only-prerelease
  tags (ignored), mixed majors, private-URL-with-key plumbing (mock the
  subprocess call).

---

## Phase 3 — Migration framework

**Difficulty: High**

**Goal:** a documented contract for how the Lens repo ships a major-version
migration, and a runner that can execute one against a project's data.

- Convention (document in this file's "Migration authoring" section below,
  and in `docs/testing.md` or a new `docs/migrations.md` if it grows):
  Lens repo ships `lens/migrations/v<N>_to_v<N+1>.py`, each exposing:
  ```python
  def migrate(project_root: Path) -> MigrationResult:
      """Mutate files under project_root in place. Raise MigrationError on
      unrecoverable problems. Must be idempotent-safe to re-run (CI may retry)."""
  ```
  `MigrationResult` carries a human-readable summary (shown in the app's
  approval banner) and a list of changed paths (for the diff view).
- `lens/core/release/migrate.py`:
  - `resolve_migration_chain(from_major, to_major) -> list[ModuleType]` —
    supports jumping multiple majors by chaining `v1_to_v2`, `v2_to_v3`, etc.
  - `run_migration_chain(project_root, chain) -> list[MigrationResult]`,
    aggregating summaries.
- `lens release migrate --to <tag>` (new CLI, `lens/cli/commands/release.py` +
  `lens/core/commands/release.py`): shallow-clones the Lens repo at `<tag>`
  into a temp dir (or, when running inside CI, the checkout IS already at
  that tag — support both: an optional `--migrations-from <path>` to point at
  an already-checked-out Lens tree, falling back to a fresh temp clone), loads
  the chain from `data_major_version` → target tag's major, runs it against
  the **project's** working tree (not the Lens checkout), then:
  - stages + commits the changed files
  - sets `migration_pending = true`, `migration_target_version = <tag>`,
    `migration_commit = <sha>` in the same commit
  - pushes (reuses `Storage.commit` + `Storage.push_or_raise`, same as
    `lens checkpoint`)
- Tests: fake migration modules in a test-only package (mirrors
  `datasets/testing/` pattern), fixture project repo (reuse
  `lens.testing.project.setup_test_project`), assert the resulting commit,
  pending-state fields, and idempotency on re-run.

---

## Phase 4 — Release decision engine (`check` / `apply`)

**Difficulty: High**

**Goal:** the CLI surface CI actually calls, with a JSON contract for
branching in a pipeline.

- `lens release check` — reads config + live status (Phase 2), and:
  1. If `migration_pending` and not yet `migration_approved`: exit 0, JSON
     `{"action": "await_approval", ...}`, do nothing else.
  2. Else pick a target tag per decision #4 above (explicit
     `requested_version` wins if set and newer than installed; otherwise
     `auto_update` policy ceiling; `off` → no target).
     - Reject (non-zero exit, clear error) a `requested_version` older than
       the currently installed tag or an unparseable tag — never silently
       downgrade.
  3. No target / already installed: JSON `{"action": "none"}`.
  4. Target major == `data_major_version`: JSON
     `{"action": "apply", "target": "<tag>"}`.
  5. Target major > `data_major_version`: JSON
     `{"action": "migrate", "target": "<tag>"}` (CI then calls `lens release
     migrate --to <tag>` from Phase 3).
- `lens release apply --to <tag>` — for the no-migration-needed path only:
  validates target major == `data_major_version` (refuses otherwise — must go
  through `migrate`), and simply prints the build parameters CI needs
  (Lens repo URL + tag to check out) as JSON. **Makes no commit** (decision
  #2) — matches "tag-based, no commit needed" literally.
  - Exception: if this `apply` is *fulfilling* a previously approved
    migration (i.e. `migration_approved == true` and `migration_target_version
    == tag`), it also clears `migration_pending` /
    `migration_target_version` / `migration_commit` /
    `migration_approved` and bumps `data_major_version` to the target's
    major, in one commit+push. This is the only case `apply` commits.
- All output is JSON on stdout, human summary on stderr, so CI YAML can do
  `RESULT=$(lens release check --json)` and branch on `.action`.
- Tests: integration-style, using the Phase 2/3 fixtures; cover all five
  branches above plus the downgrade-rejection case.

---

## Phase 5 — App-side server routes

**Difficulty: Medium**

**Goal:** the deployed app can read status and mutate policy/approve
migrations; no UI yet (routes + tests only).

- `lens/server/routes/release.py`:
  - `GET /{slug}/release/status` → `compute_release_status` (Phase 2) as JSON:
    enabled, installed (from `LENS_VERSION` env, `None` if unset), latest
    available (live check, short in-process TTL cache — e.g. 5 minutes),
    auto_update policy, requested_version, data_major_version, migration
    pending info (+ diff via `storage.diff()`/`git show` on the pending
    commit when applicable).
  - `POST /{slug}/release/policy` `{auto_update?, requested_version?}` →
    updates `[release]` in `lens.toml` and commits+pushes via `Storage`
    (mirrors `execute_checkpoint`).
  - `POST /{slug}/release/migration/approve` → sets `migration_approved =
    true`, commits+pushes.
  - `POST /{slug}/release/migration/reject` → reverts the migration commit
    (if it's still the tip; otherwise raise a clear conflict error asking the
    user to resolve manually) and clears pending fields, commits+pushes.
  - All routes 404 with a clear message when `[release]` is absent/disabled
    (matches Phase 1's "no-op" default).
- No business logic in routes — all of the above lives in
  `lens/core/commands/release.py`, routes just validate + call + map
  exceptions to HTTP errors (per the server rules in `CLAUDE.md`).
- Tests: `lens/server/test/` route tests using the existing test-client
  fixtures; a fake bare-git-remote fixture for the live tag check (Phase 2).

---

## Phase 6 — UI: Release panel

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
  version" button), and — when `migration_pending` — a prominent banner with
  the migration summary/diff and Approve/Reject buttons.
- Wire into the existing settings/layout surface (find where `stats` or
  similar project-level info is already surfaced — likely a settings route or
  sidebar section; follow the existing `MainLayout.svelte` structure, do not
  redefine layout).
- Tests: Vitest component/store tests (`poe test-ui`); one Playwright e2e
  happy-path (policy change persists; migration approve banner appears and
  clears) added to `e2e/tests/test_browser.py` or a new
  `test_release_browser.py`, following the regression-fixture pattern in
  `e2e/fixtures/README.md`.

---

## Phase 7 — Dataset repo runtime sync

**Difficulty: High**

**Goal:** `[[dataset_repo]]` entries are cloned onto the Fly volume and kept
up to date via the existing refresh mechanism; no CI involvement required.

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
Phase 3/4 CLI commands.

- `deploy/ci/github-release.yml` (template to copy into a project repo's
  `.github/workflows/`): triggers on push to main + a schedule (e.g. hourly).
  Steps: checkout project repo, install `lens` (pinned to whatever tag/commit
  the project is currently tracking — bootstrap problem: the *runner*
  installing `lens` needs a working Lens install to even run `lens release
  check`; install from `data_major_version`'s compatible tag or `main` — call
  this out as an explicit bootstrap rule in the doc), run `lens release
  check --json`, branch on `.action`:
  - `apply`: checkout Lens repo at target tag into a build context, `flyctl
    deploy` with `--build-arg LENS_VERSION=<tag>` (needs `FLY_API_TOKEN`
    secret).
  - `migrate`: run `lens release migrate --to <tag>`, stop (approval happens
    in-app).
  - `none`/`await_approval`: no-op.
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
- Tests: these are YAML templates, not Python — validate with a lint
  (`actionlint` for the GitHub template if available, `gitlab-ci` linter via
  their API is out of reach in this repo's test suite) or, at minimum, keep
  them out of `poe check`'s scope and cover the underlying CLI commands they
  call with the Phase 3/4 tests instead. Add one e2e test that shells out the
  exact command sequence a pipeline would run (not the YAML itself) against a
  fixture project + fake upstream repo, to catch drift between the docs and
  reality.

---

## Phase 10 — End-to-end validation & docs polish

**Difficulty: High**

**Goal:** everything wired together, documented, and exercised as a whole.

- One full e2e test (`e2e/tests/test_release_regression.py` or similar):
  fake upstream Lens repo (bare git repo with `v1.0.0`, `v1.1.0`, `v2.0.0`
  tags and a fake `v1_to_v2` migration module available at the right path),
  fake project repo, walks through: check → apply (minor) → check → migrate
  (major) → app-side approve (via the Phase 5 routes) → check → apply
  (major, commits + bumps `data_major_version`). Also a fake dataset repo
  exercising Phase 7's refresh path.
- Update `CLAUDE.md` doc map with a row pointing to this file (or fold the
  finished design into `docs/configuration.md` / `deploy/README.md` and
  retire this file — decide at Phase 10 time based on how large the final
  reference docs get).
- Follow-ups to file as separate issues, not part of this plan: automatic
  rollback of a bad deploy/migration; non-Fly deployment stacks; dataset
  extension code version-gating; multi-major auto-chaining UX (currently: CI
  computes a single chain and runs it in one `migrate` call — fine for now,
  but a UI that shows *each* intermediate major's migration summary
  separately would be nicer for review).

---

## Migration authoring (reference for Lens repo maintainers, written up fully in Phase 3)

When cutting a major version tag that requires a data migration:

1. Add `lens/migrations/v<N>_to_v<N+1>.py` with a `migrate(project_root: Path)
   -> MigrationResult` function.
2. Keep it idempotent-safe — CI may re-run `lens release migrate` after a
   transient failure.
3. Tag the release as usual (`git tag vN+1.0.0 && git push --tags`) — no
   separate "register this migration" step; the chain resolver
   (Phase 3) discovers modules by the `v<from>_to_v<to>.py` naming
   convention.
</content>
