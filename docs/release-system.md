# Release system: project-centric cloud deploy & upgrade

Implements GitHub issue **#55 — "Project-centric cloud deploy (not from Lens repo)"**.

Today, deploying and upgrading Lens (`deploy/README.md`) requires a desktop with a
checked-out copy of the Lens tool repo: `lens deploy push` builds the Docker image
from your local clone and pushes it to Fly. There is no way to deploy or upgrade
a project from CI alone, and no way to auto-update either the Lens application or
the external datasets a project depends on.

This document has two parts: the **target design** (what the finished system
should do and why), and the **baseline** (what already exists on this branch),
followed by the phases that take the baseline to the target design. Everything
described here lives on an unmerged branch — nothing below has ever been
deployed for real, so there is no back-compat story to preserve. Read the
whole document before starting Phase 1.

**This file is a working plan and is deleted before this branch merges — it
is not shipped documentation.** The two files that *are* shipped
documentation and must stay accurate throughout every phase are
**[deploy/README.md](../deploy/README.md)** and
**[docs/configuration.md](configuration.md)**. Both currently describe the
*old* `[release]` shape (including `gated_update_*` fields that this plan
removes). Every phase below that changes `[release]`'s schema or behavior
says explicitly which of these two files it must update — treat that as a
hard requirement of the phase, not an optional cleanup step, since nothing
in *this* file will exist to catch drift after it's deleted.

## Non-goals (explicitly out of scope for this plan)

- Replacing or changing the existing desktop `lens deploy` command family. It
  stays exactly as documented in `deploy/README.md`; everything here is additive.
- Deployment stacks other than Fly.io. The apply/deploy step is Fly-specific;
  the version decision engine is stack-agnostic.
- Automatic rollback of a bad release. Out of scope; noted as a follow-up in
  Phase 5.
- **Any retry, staleness-detection, or "this update seems stuck" heuristic.**
  Decision #3 below is deliberately a single fire-and-forget write: the app
  writes the request once, CI gets exactly one shot at it (decision #4), and
  that's the entire mechanism for v1. If a deploy doesn't happen — a CI
  failure, the workflow disabled, whatever — nothing in this system notices
  or retries automatically. The operator already has manual escape hatches
  (re-run the CI workflow by hand, or fall back to desktop `lens deploy
  push`), and a future version can add a "some N commits and T time have
  passed and `installed` still doesn't match `requested_version`, are you
  sure this applied?" warning once it's clear what that heuristic should
  actually be. Don't build it speculatively now.
- **Data migration.** Every version bump — patch, minor, or major — is
  surfaced and requires an explicit human click in the app before it's
  deployed (see decision #3), but this plan assumes project data needs no
  transformation across versions — approving is a plain "go ahead and
  deploy this" click, nothing more. Actually mutating project data when a
  future major version requires it is spun off to a future feature: **#88**.
- Dataset **code** (Python extensions) version-gating against Lens major
  versions. Per the issue, dataset repos are always auto-updated to their
  latest commit on their tracked ref, no version compatibility system. If a
  dataset ships an extension package, keeping it working across Lens versions
  is the dataset author's problem, not this system's.
- Automatic election or failover of the release leader in a multi-project
  Fly deployment (decision #8). Designating (and re-designating, if the
  leader project is ever removed) `[release] app_leader = true` is a manual,
  one-time operator action, not something the system infers.
- Any policy or filtering config for *which* new versions get surfaced (e.g.
  "only notify me about major bumps"). There is no `auto_update` field or
  equivalent in this plan's schema (decision #3) — every deploy is
  human-requested, full stop. If a filtering feature is wanted later, it
  gets its own new field designed at that time; nothing is pre-reserved for
  it now.

## Key design decisions

These resolve ambiguity in the issue text; call them out explicitly so
reviewers can push back before implementation starts. This is the **target
design** — some of it is already true of the code on this branch (the
baseline below says exactly which parts), some of it isn't yet.

1. **State lives in `lens.toml`, not a separate file — and CI never writes
   to it, under any circumstance.** A new `[release]` table and
   `[[dataset_repo]]` array. Git is the only channel between the app and CI;
   there is no shared runtime state. **The app is the only writer, ever.**
   Its write (recording a human-requested update, decision #3) is an
   ordinary `Storage.write_file` mutation — uncommitted, swept into the
   user's next checkpoint exactly like any other pending edit (a pin, a
   param change, anything). It never commits or pushes on its own, so it
   can never collide with, or be blocked by, whatever else is uncommitted in
   that session. CI only ever *reads* `[release]` from its own checkout —
   see decision #4 for exactly why a read-only CI can still be the thing
   that triggers a deploy exactly once, with nothing to commit back.

2. **Minimize persisted state — prefer live checks.** Exactly two facts
   need to survive a page reload or an independent CI run, and they're
   written together, once, by the app (decision #3):
   - `requested_version` — the target tag (empty = nothing requested).
   - `requested_from_commit` — the exact commit hash that was `HEAD` at the
     moment the request was written. This is what makes decision #4's
     "deploy exactly once" possible without CI ever writing anything back.

   Everything else is computed live, every time, by whoever needs it, and
   never committed:
   - **"Currently installed"** — read from the running container's own
     `LENS_VERSION` environment variable, baked in at Docker build time
     from the git tag CI checked out. The deployed app reads this directly
     from its own process environment — trivial, no network call.
   - **"Latest available"** — computed on demand via `git ls-remote --tags`
     against the tracked Lens repo URL (no auth needed for public repos;
     same SSH deploy-key mechanism as project repos for private forks).
      **The deployed app performs this check itself, on demand**, only when
      the user triggers a project-level action (stats, refresh, or checkpoint)
      — no TTL cache needed because it's computed at most once per explicit
      user request. CI never needs to query the Lens repo's tags at all.

3. **Every deploy is explicitly requested by a human in the app UI, via a
    single write — no autonomous deploy, and no follow-up bookkeeping after
    that write.** Whenever the user triggers a project-level action (stats,
    refresh, or checkpoint), the response includes release status — the app
    compares the live "latest available" tag (decision #2) against its own
    installed version. If there's a newer one, the UI shows a plain
    notification — "vX.Y.Z is available" — with an Update action. **This is the same
   notification for a patch, a minor, or a major bump; none of them are
   ever applied silently.** Any deploy rolls the running container, and
   that can disrupt whatever the user is doing mid-session (an in-flight
   LLM call, an open generation) — that's not a risk to take without the
   user's own say-so, no matter how small the version difference looks. If
   a newer tag appears while an older one is still un-actioned, the
   notification simply shows the newest one; there's no queue of skipped
   versions to work through later.

   Clicking **Update** writes `requested_version = <tag>` **and**
   `requested_from_commit = <current HEAD hash>` into `lens.toml` in one
   go — the plain, uncommitted write described in decision #1. It does
   **not** trigger an immediate checkpoint. If a checkpoint happens to be
   pending or in progress when the user clicks, the request rides along
    with it; if not, it just sits as a normal pending edit — exactly like a
    pin or a param change — until whatever the user's *next* checkpoint
    turns out to be, whenever that happens. This deferral is deliberate:
    triggering a checkpoint-and-push while an LLM stream is open, or while
    the user has pending unsaved composition, would break the app and
    (at best) waste money on a mid-stream checkpoint. The release system
    yields to the user's editing session, not the other way around.
    Nothing about the release system forces a checkpoint to happen sooner.
    (A "checkpoint now" convenience
    button for this specific case is a plausible future UI nicety, not part
    of this plan.)

   **That single write is the entire app-side mechanism — there is
   deliberately no follow-up.** Nothing ever clears `requested_version` or
   `requested_from_commit` after the fact, and nothing needs to: decision
   #4's parent-hash check can only ever match the one specific commit that
   turns out to be the immediate child of `requested_from_commit`. Once
   that commit exists — whether or not the resulting deploy actually
   succeeded — no other commit, ever, can have that same parent, so the
   request is permanently spent either way. Leaving the stale fields
   sitting in `lens.toml` forever is completely harmless; there's no
   dangling state to clean up and no reason to spend a write doing so. See
    the non-goals above for why there's also no retry/re-arm logic for the
    failure case. The UI already knows its own `installed` version (from the
    same stats/refresh/checkpoint response), so after a deploy completes, the
    next user action naturally shows `requested_version == installed` — the
    notification switches from "Update requested" to "Update applied" with no
    additional state or commit needed. Any outcome other than an exact match
    (deploy failed, CI never ran, etc.) leaves `installed` unchanged, so the
    notification persists as "Update requested" until/unless the human
    intervenes.

4. **CI's job is a single, stateless, read-only check: does the commit I'm
   building for have `requested_from_commit` as its exact parent?** If so,
   deploy `requested_version`; if not, do nothing. That's the entire
   decision — no policy evaluation, no comparison against "installed" (CI
   has no reliable way to know that anyway, and doesn't need to), and
   **no write back to git, ever, under any circumstance:**
   - `lens release check --json` reads `requested_version` and
     `requested_from_commit` from the checkout CI already has. Empty
     `requested_version` → `{"action": "none"}`. Otherwise, it checks
     whether `requested_from_commit` is the exact parent of the commit(s)
     introduced by the triggering push (see the multi-commit-push note in
     Phase 4 — a push can carry more than one new commit at once, so this
     has to check the whole `before..after` range, not just the tip). Match
     → `{"action": "apply", "target": "<tag>"}`. No match (this includes:
     nothing requested, the opportunity already passed on an earlier
     commit, or the request hasn't reached this checkout's ancestry yet)
     → `{"action": "none"}`.
   - `lens release apply --to <tag>` prints the build parameters CI needs
     (Lens repo URL + tag to check out) as JSON, same as before. CI runs
     `flyctl deploy` with that tag. **Nothing is written back to the
     project repo at any point** — not a commit, not a clear, nothing.
   - Because the trigger condition is keyed to one specific commit's parent
     hash — a fact of git history that can only ever be true once — there
     is no shared mutable state for two CI runs to race over, and therefore
     no correctness reason for runs to queue or serialize. (A concurrency
     group is still reasonable CI hygiene to avoid two unrelated runs
     wasting parallel build minutes, but it's not solving a bug — there
     isn't one to solve.)

5. **Dataset repos are tracked but never version-gated.** They're cloned onto
   the same Fly volume as project repos (extending the existing `start.sh`
   clone/fast-forward logic), not baked into the Docker image. "Auto-update"
   for a dataset is exactly the existing content **Refresh** mechanism
   (`git fetch` + fast-forward), extended to also run against each
   `[[dataset_repo]]` clone. No image rebuild, no CI build required in the
   common case. **There is no scheduler anywhere in this system** — refresh
   is triggered either by an explicit user/API action (the existing Refresh
   button) or, organically, as one more step of the same push-triggered CI
   run described in decision #6 (never a separate cron or timer). This is a
   large scope reduction versus the Lens-version engine and reuses
   infrastructure that already exists.

6. **CI mechanics are provider-neutral; only the trigger/secrets glue is
   provider-specific.** All decision logic lives in `lens release *` CLI
   subcommands (plain Python, testable without any CI runner). GitHub Actions
   and GitLab CI each get a thin, mostly-declarative pipeline file that only
   handles triggers, secrets, and calling those CLI commands + `flyctl`. This
   matches the user's own project layout (Lens tool repo on GitHub, project
   repos on GitLab) and forces the core to stay host-agnostic.

7. **Desktop `lens deploy push` computes `LENS_VERSION` from local tags, not
   `git describe`.** It reads the Lens repo checkout's own tags, finds the
   latest release tag, and:
   - if `HEAD` **is** that tag's commit → `LENS_VERSION = <tag>` (e.g.
     `v1.4.2`) — a clean release build.
   - if `HEAD` is **not** that tag's commit (you're ahead of the last tag,
     mid-development) → `LENS_VERSION = <tag>+<short-hash>` (e.g.
     `v1.4.2+a1b2c3d`) — using `+` (semver build metadata) rather than `-`
     since this isn't a formal pre-release channel, just "last known tag,
     plus this exact commit." This is informational only — the release
     decision engine never parses or compares this value, it only reads
     remote tags. Practically, this is what lets you `lens deploy push` a
     not-yet-tagged commit straight from your desktop checkout for manual
     testing, while still being able to tell at a glance which release
     lineage it's based on.
   - no tags at all in the checkout → `LENS_VERSION = 0.0.0+<short-hash>`.

8. **A multi-project Fly app designates exactly one release leader; there is
   no cross-project reconciliation.** `deploy/README.md` documents a
   parent-of-projects `fly.toml` topology (either as a bare directory, or
   colocated inside the leader's own project directory) — one Fly app, one
   deployed Lens binary, several project repos underneath it, possibly on
   different Git hosts entirely. But there is only **one** `LENS_VERSION`
   for that whole app, so the `[release]` state (decision #1) can't
   independently live in every served project's own `lens.toml` — two
   sibling projects' CI pipelines could show conflicting notifications for a
   version that only one of them actually controls. Rather than inventing a
   new app-level config file/repo, exactly one served project is flagged
   `[release] app_leader = true`; its `lens.toml` is the single source of
   truth for that Fly app, and only its CI pipeline is wired up to run
   `lens release apply` + `flyctl deploy` (Phase 4). Server routes resolve
   to the leader's config regardless of which project's slug was in the
   request URL, so every served project's UI shows/controls the identical
   shared state — there's no "wrong project" error. This is a manual,
   one-time designation: there's no automatic election or failover if the
   leader project is ever removed from the deployment (`lens deploy
remove`) — the operator must re-flag a new leader by hand. Single-project
apps are entirely unaffected; `app_leader` defaults to `false` and is
never set because a lone served project is trivially the leader — the
field only enters the picture when a second project is added to the
deployment.

## Config schema (target shape)

This is the **entire** `[release]` table — five fields, nothing else:

```toml
# lens.toml

[release]
enabled               = true
lens_repo_url         = "https://github.com/danielepagano/lens.git"  # default; override for a fork
requested_version     = ""  # e.g. "v2.1.0"; set once by the app UI's Update click, or manually. Never cleared — see decision #3.
requested_from_commit = ""  # full commit hash that was HEAD when requested_version was set; CI deploys exactly the next commit whose parent is this hash — see decision #4.
app_leader            = false  # only relevant (and must be true on exactly one project) when
                              # this Fly app serves >1 project — single-project apps never set this

[[dataset_repo]]
name    = "lens-dnd"
git_url = "git@gitlab.com:org/lens-dnd.git"
ref     = "main"
```

`installed_version` and `latest_available_version` are **not** stored here —
see decision #2. There is **no** `auto_update` field and **no**
`gated_update_*` field anywhere in this target shape — see non-goals above
and the baseline below for what's actually on this branch instead. Any
`[release]` schema documentation outside this file — **`deploy/README.md`**
and **`docs/configuration.md`** — must match exactly this: `enabled`,
`lens_repo_url`, `requested_version`, `requested_from_commit`, `app_leader`,
and nothing more.

## Architecture at a glance

```
Deployed Lens app (Fly)                         Project repo (git)              CI (GitHub Actions / GitLab CI)
------------------------                        ------------------              --------------------------------
reads LENS_VERSION env  <--------------------- (baked at image build) <-------- checks out Lens repo at target tag,
  "currently installed"                                                          builds image, fly deploy

live git ls-remote  ------------------------> Lens repo tags (GitHub, any fork)
  "latest available" (app checks this itself, on demand — stats/refresh/checkpoint — CI never does)

shows notification, human clicks Update
  --> writes requested_version = <tag>,   -->  lens.toml [release]
      requested_from_commit = <HEAD>            |
        (one plain uncommitted file write,      | swept into the user's next
         no push — decision #1/#3)              | checkpoint, whenever that is
                                                 v
                                           pushed to tracked branch  ------->  triggers CI (push, decision #6)
                                                                                   |
                                                                                   v
                                                                             lens release check
                                                                             (reads requested_version /
                                                                              requested_from_commit from
                                                                              its own fresh checkout)
                                                                                   |
                                                              parent of this push's commit(s)
                                                              == requested_from_commit?
                                                                   |            |
                                                                  yes           no
                                                                   |            |
                                                            flyctl deploy   {"action":"none"}
                                                          (no write back to git — ever;
                                                           decision #1/#4, this is the
                                                           whole point)

Refresh action  -----------------------> project + [[dataset_repo]] clones on volume  <---- user action, or one more
  (user-triggered, or a step of a push-triggered CI run — never scheduled)                    step of the same push-triggered CI run
```

This diagram is the single-project case (one Fly app, one project repo). For
a Fly app serving several projects (decision #8), "Project repo" / "CI" on
the right only exist for the one project flagged `app_leader = true` —
siblings have no `[release]` state and no release-triggering CI at all; the
deployed app's server routes still resolve to the leader's `lens.toml`
regardless of which served project's UI made the request.

## Baseline (already on this branch)

Everything below is committed on this branch and never merged or deployed —
there is no live user relying on any of it, so nothing here needs a
migration path, only replacement where the phases below say so.

- **`lens/core/release/config.py`, `version.py`, `status.py`** — `[release]`/
  `[[dataset_repo]]` parsing, semver tag resolution (`list_remote_tags`,
  `latest_within_major`, `latest_overall`), `installed_version()`, and
  `compute_release_status()`. The config currently includes `auto_update`
  and `gated_update_pending` / `gated_update_target_version` /
  `gated_update_approved` alongside the still-correct `enabled` /
  `lens_repo_url` / `requested_version` / `app_leader`. There is **no**
  `requested_from_commit` field on this branch yet — it's new. **`auto_update`
  and all three `gated_update_*` fields, and everything that reads or writes
  any of them, are removed by Phase 1 below; `requested_from_commit` is
  added** — the target schema (above) is exactly the five fields that
  result.
- **`lens/core/commands/release.py` + `lens/cli/commands/release.py`** —
  `lens release check`/`apply` currently implement a target-selection engine
  (`_select_target_tag`: `auto_update` policy ceiling vs. explicit
  `requested_version`, a major/minor boundary check) plus a
  `gated_update_pending`/`gated_update_approved` handshake, written via
  plain `git commit`/`git push` against the checked-out `project_root`
  (`_git_commit_and_push`). **`check`/`apply` are rewritten wholesale** by
  Phase 1 (decision #4) — critically, the branch's current `apply` *does*
  commit; the target design's `apply` never does.
- **`lens/server/routes/release.py`** — `GET /release/status`, `POST
  /release/policy`, `POST /release/gated-update/approve`, `POST
  /release/gated-update/reject`, writing via `session.new_storage(owner=None)`
  + `Storage.commit()`/`push_or_raise()`. The gated-update routes and
  `status` are **removed**; release fields are folded into `GET /stats`
  instead (computed on demand, no TTL), and a new plain-write `POST
  /release/request` route is added by Phase 2 (decision #1/#3).
- **`lens/server/ui/src/features/release/{ReleaseModal,ReleaseNotification}.svelte`**
  — a settings-style panel (policy controls) plus an approve/reject banner.
  **Replaced** by a single notification + button by Phase 3 (decision #3).
- **`deploy/start.sh`** dataset-repo clone/fast-forward loop (keyed by
  `DATASET_REPO_DEPLOY_KEY_<NAME>`) and **`deploy/Dockerfile`**'s `ARG
  LENS_VERSION=dev` / `ENV LENS_VERSION=${LENS_VERSION}` — both **unaffected**
  by this redesign (decision #5 and decision #2/#7 respectively); nothing to
  do here.
- Multi-project leader resolution — `validate_deploy_topology`,
  `resolve_release_project_root`, `find_release_leader_slug`,
  `_validate_release_topology` in `lens/core/commands/deploy.py` — also
  **unaffected** (decision #8); nothing to do here.
- No CI pipeline templates exist yet (`deploy/ci/`) — net new, Phase 4.

## Phase difficulty at a glance

Only the work remaining to take the baseline above to the target design.
Rated on how much novel design judgment, cross-cutting/moving parts, and
hard-to-test surface area is involved — not raw line count.

| Phase | Title | Difficulty | Why |
|-------|-------|------------|-----|
| 1 | Simplify the release decision engine | **Low** | Net deletion of the policy/gating state machine and the git-write path, replaced by a stateless, read-only parent-hash check; smaller and simpler than what's there today, not an extension of it. |
| 2 | App-side server routes | **Low** | Drop four routes, plumb release fields into existing `GET /stats`, add one plain-write route with no commit/push involved — smaller than what's already there. |
| 3 | UI: single update notification | **Low** | One notification + one button, no diff review, no policy selector. Smaller than the panel it replaces. |
| 4 | CI reference pipelines (GitHub + GitLab) | **High** | Two separate CI systems and real Fly deploys; the pipeline logic itself is trivial (decision #4), but secrets/host-specific glue and the multi-commit-push edge case are only discoverable by running it for real. |
| 5 | End-to-end validation & docs polish | **High** | Large integration test tying every phase together; not novel design, but any gap upstream surfaces here first. |

---

## Phase 1 — Simplify the release decision engine

**Difficulty: Low**

**Goal:** `lens release check`/`apply` match decision #4 exactly — a
stateless, read-only parent-hash check. **`[release]`'s schema becomes
exactly the five fields in the target config schema above** — this phase is
also where `deploy/README.md` and `docs/configuration.md` get corrected to
match; do not leave either describing the old shape.

- `lens/core/release/config.py`: remove `auto_update`, `gated_update_pending`,
  `gated_update_target_version`, and `gated_update_approved` from
  `ReleaseConfig` entirely (and the corresponding parsing/validation in
  `lens/core/commands/check.py`); add `requested_from_commit: str = ""`.
  `ReleaseConfig` ends up with exactly `enabled`, `lens_repo_url`,
  `requested_version`, `requested_from_commit`, `app_leader`.
- `lens/core/commands/release.py`: delete `_select_target_tag`,
  `_mark_gated_pending`, the major/minor boundary logic, and
  `_git_commit_and_push`/`_run_git` entirely — nothing in this module writes
  to git anymore. Rewrite `execute_release_check`/`execute_release_apply` to
  the shape in decision #4:
  - `check`: read `requested_version`/`requested_from_commit` from the local
    checkout. Empty `requested_version` → `{"action": "none"}`. Otherwise,
    determine the parent commit(s) of what's being checked (see Phase 4 for
    how the CLI is given the relevant commit range) and compare against
    `requested_from_commit`; exact match on any of them →
    `{"action": "apply", "target": tag}`; no match → `{"action": "none"}`.
    A basic "does `requested_version` parse as `vMAJOR.MINOR.PATCH`" sanity
    check is still worth keeping (so a garbaged value fails loudly instead
    of reaching `flyctl` with nonsense); there is **no** comparison against
    "installed" — CI doesn't reliably know that, and doesn't need to.
  - `apply --to <tag>`: unchanged in spirit — prints `{lens_repo_url, tag}`
    as JSON. **No commit, ever, in any case.** There is no
    `--confirm-deployed` flag, no clearing step, nothing written back.
- `lens/cli/commands/release.py`: drop any CLI surface for the removed
  gated fields (e.g. an `approve`/`reject` CLI mirror, if one exists).
- **`docs/configuration.md`** (real, shipped docs — see the callout at the
  top of this file): rewrite the `[release]` / `[[dataset_repo]]` section's
  intro (it currently says "auto-update policy, Lens version tracking..." —
  there is no auto-update policy) and schema table down to exactly `enabled`,
  `lens_repo_url`, `requested_version`, `requested_from_commit`, `app_leader`
  — remove the `auto_update` and all three `gated_update_*` rows entirely,
  don't just mark them unused; add a row for `requested_from_commit`
  explaining the parent-hash mechanism in one sentence. Update
  `requested_version`'s description to mention the UI's Update button as
  the common path and that it's never cleared automatically. Also fix the
  `lens check` validation table further down that page — it currently lists
  "`auto_update` values" as something `lens check` validates; remove that.
- **`deploy/README.md`** (real, shipped docs): it currently calls this "the
  release/auto-update system" (Initial Setup section) — reword to "the
  release system" (or similar) now that there's no autonomous auto-update
  behavior to name it after.
- Tests: delete/rewrite `lens/core/test/test_release_commands.py`'s
  gated-approval-flow and target-selection-policy cases entirely; add cases
  for the new shape (no request; request whose parent matches → apply;
  request whose parent doesn't match, e.g. a later, unrelated commit still
  carrying the same stale fields forward → none; unparseable-tag rejection).
  Assert `execute_release_apply` never touches git (no subprocess `commit`/
  `push` calls at all — a good regression guard, since the whole point of
  this phase is that CI stops writing). Multi-project topology tests
  (`resolve_release_project_root`, `validate_deploy_topology`) are unaffected
  — keep as-is.

---

## Phase 2 — App-side server routes

**Difficulty: Low**

**Goal:** the deployed app can record a human's request to deploy a new
version, and surface release info in existing project-level responses
rather than a dedicated polled route.

- `lens/core/release/status.py`: update `ReleaseStatus`/`compute_release_status`
  to match the trimmed config — drop gated/policy fields, add
  `requested_from_commit`. This internal model is used by the stats endpoint,
  not by a standalone route.
- `lens/server/routes/release.py`:
  - Remove `GET /release/status`, `POST /release/policy`, `POST
    /release/gated-update/approve`, and `.../reject` entirely. `status` had
    a dedicated poll with TTL-cached `latest_available` — that is replaced
    by folding release fields into the existing `GET /stats` response.
  - `lens/core/commands/release.py`: remove `execute_release_policy_update`,
    `execute_release_gated_approve`/`_gated_reject` — `auto_update` no
    longer exists to have a policy route for, and there's no more
    approve/reject handshake (decision #3/#4).
  - **`GET /stats`** (in `lens/server/routes/`): add release fields to the
    response — `releases_enabled`, `installed_version`, `requested_version`.
    `latest_available` is computed synchronously on this call via
    `git ls-remote --tags` against the Lens repo URL (no TTL — this only
    fires when the user explicitly asks). `requested_from_commit` is an
    implementation detail CI needs, not UI-facing — leave it out.
  - Add `POST /release/request` `{target_version}`: validate
    `target_version` matches `vMAJOR.MINOR.PATCH` (same sanity check Phase 1
    uses in `check`) and isn't older than `installed` (this is exactly where
    that check belongs — the app has a reliable `installed` value; CI, per
    decision #4, does not), then call a new
    `execute_release_request(session, target_version)` that reads the
    session's current `HEAD` commit hash and does a single
    `session.new_storage(owner=None).write_file(lens_toml, updated)` writing
    **both** `requested_version` and `requested_from_commit` — **no
    `.commit()`, no `.push_or_raise()`**. This one write is the entire
    implementation of decision #3.
  - Multi-project leader resolution (`_release_session`) is unaffected —
    keep as-is.
- Tests: `lens/server/test/test_release.py` — remove status/policy/approve/
  reject route tests; update stats tests for the added release fields; add
  a request-route test that mocks `Storage` and asserts `write_file` was
  called with both fields and that `commit`/`push_or_raise` were **not**
  called.

---

## Phase 3 — UI: single update notification

**Difficulty: Low**

**Goal:** one small, honest notification. No settings panel, no policy
selector, no approve/reject banner, no dedicated release status poll —
decision #3 removed the need for any of them.

- Replace `ReleaseModal.svelte`'s settings panel and `ReleaseNotification.svelte`'s
  approve/reject banner with a single component: "vX.Y.Z is available" +
  an **Update** button (calls `POST /release/request`) + **Dismiss**
  (local-only; reappears the next time the user triggers a stats/refresh/
  checkpoint action since nothing was written — decision #3 explicitly
  allows ignoring it). Once `requested_version` is set (per the `GET /stats`
  release fields), show "Update requested — will apply on your next
  checkpoint" instead; there's no further status to track beyond that (no
  pending/approved distinction, decision #3).
- No `services/releaseService.ts` or `stores/releaseStore.ts` with a
  separate release status fetch — release info is embedded in the existing
  `GET /stats` response that the UI already reads. Drop policy/approve/
  reject state entirely; the only new call is `POST /release/request`.
- Wire into the existing settings/layout surface, following
  `MainLayout.svelte` conventions as before.
- Multi-project cosmetic note (decision #8) — "this update applies to all N
  projects on this deployment" — carries over unchanged if already present,
  otherwise skip; not essential.
- Tests: update Vitest component/store tests (`poe test-ui`) for the new
  component; update or replace the Playwright e2e happy-path (click Update,
  stats response reflects the pending request, no commit happens).

---

## Phase 4 — CI reference pipelines (GitHub Actions + GitLab CI)

**Difficulty: High**

**Goal:** two ready-to-copy pipeline templates. Per decision #4, these are
deliberately thin — no policy logic, no HTTP calls to the deployed app, no
scheduler, and **CI never writes to git**. Net new; nothing on this branch
touches CI yet.

- `deploy/ci/github-release.yml` (template to copy into a project repo's
  `.github/workflows/`): **triggers on `push` to the tracked branch only —
  no schedule, no cron, ever** (decision #5). Checkout step needs enough
  history to compute parent hashes — **do not use the default shallow
  checkout**; fetch at least the commits introduced by this push plus one
  more (e.g. `fetch-depth: 0` for simplicity, or a depth just past
  `github.event.before`). Steps: checkout project repo, install `lens` (see
  issue #56 for the version-pin bootstrap rule), run `lens release check
  --json` — passing it the push's commit range (e.g.
  `--since ${{ github.event.before }}` or equivalent, so it can check every
  commit introduced by this push, not just the tip; **a push can carry more
  than one new commit**, and the one whose parent matches
  `requested_from_commit` might not be the tip — get this right, it's the
  one real correctness subtlety in an otherwise trivial pipeline) — then
  branch on `.action`:
  - `apply`: checkout Lens repo at target tag into a build context, `flyctl
    deploy` with `--build-arg LENS_VERSION=<tag>` (needs `FLY_API_TOKEN`
    secret). **That's it — no further step.** Nothing is written back to
    the project repo, committed, or pushed, on success or failure.
  - `none`: no-op.
  Also runs `curl -X POST https://<app>/<slug>/refresh` (Basic Auth
  credential as a CI secret) as one more step of this **same** push-triggered
  run, to drive dataset auto-update per decision #5 — not a separate schedule.
- No concurrency group is required for correctness (decision #4 — there is
  no shared mutable state to race on). Adding one anyway for ordinary CI
  hygiene (avoid wasting parallel Fly build minutes if, rarely, two pushes
  land close together) is a reasonable, optional addition — don't spend
  design effort on it; a plain `concurrency: { group: release-<app> }`
  (GitHub) / `resource_group: release-<app>` (GitLab) is enough if added at
  all.
- `deploy/ci/gitlab-release.yml`: identical steps/stages and the same
  push-only trigger, GitLab CI syntax (`rules: - if: $CI_PIPELINE_SOURCE ==
  "push"`, no `schedule` block at all), using `$CI_COMMIT_BEFORE_SHA`/
  `$CI_COMMIT_SHA` for the equivalent commit-range check.
- `deploy/README.md`: new "CI-driven deploy (no desktop)" section describing
  prerequisites (which secrets go where, on GitHub vs GitLab), how this
  relates to the existing desktop flow (either/or, not both against the same
  Fly app), and a link to this design doc.
- **Multi-project deploy (decision #8):** only the release *leader*
  project's repo gets this pipeline wired up to actually run `lens release
  apply` + `flyctl deploy` for the shared Fly app. Sibling project repos, if
  they have CI at all, only trigger their own content `/refresh` — never the
  Lens-version pipeline; document this explicitly as a setup instruction.
  This works even when siblings live on entirely different hosts than the
  leader, because the leader's CI never needs to know about them at all.
- Tests: these are YAML templates, not Python — validate with a lint
  (`actionlint` for the GitHub template if available) or, at minimum, keep
  them out of `poe check`'s scope and cover the underlying CLI commands with
  the Phase 1 tests instead. Add one e2e test that shells out the exact
  command sequence a pipeline would run (not the YAML itself) against a
  fixture project + fake upstream repo, **including a push that carries two
  new commits at once, where only the first has `requested_from_commit` as
  its parent**, asserting the deploy still fires correctly — this is
  exactly the multi-commit-push edge case that's easy to get wrong.

---

## Phase 5 — End-to-end validation & docs polish

**Difficulty: High**

**Goal:** everything wired together, documented, and exercised as a whole.

- One full e2e test (`e2e/tests/test_release_regression.py` or similar):
  fake upstream Lens repo (bare git repo with `v1.0.0`, `v1.1.0`, `v2.0.0`
  tags), fake project repo. Walks through: stats response shows a newer
  tag available → simulate the Update click (`POST /release/request`,
  assert no commit happened, assert both fields were written) → simulate a
  checkpoint (now both fields are committed+pushed, at some commit C1) → CI
  `check` on the push producing C1 sees C1's parent matches
  `requested_from_commit` → `apply` → deploy — **with the project's own
  working tree left deliberately dirty (an uncommitted narrative edit) for
  the entire run**, asserting this dirty state never blocks the request
  write or the checkpoint. Then simulate a **second, unrelated checkpoint**
  producing C2 (child of C1, still carrying the same stale
  `requested_version`/`requested_from_commit` forward unchanged) and assert
  CI's `check` on *that* push returns `{"action": "none"}` — proving the
  request is permanently spent after C1, with nothing having been written
  back to git to make that true. Also a fake dataset repo exercising the
  existing dataset-repo refresh path.
- **This file is deleted as part of this phase** (see the callout at the
  top) — not folded in, not retired-later. Before deleting it, do a final
  pass confirming `deploy/README.md` and `docs/configuration.md` together
  cover everything a future reader would need: the `[release]` schema
  (exactly `enabled`/`lens_repo_url`/`requested_version`/
  `requested_from_commit`/`app_leader`, no `auto_update`, no
  `gated_update_*`), the CI secrets Phase 4 introduced, and the
  update-notification UX. If something below turns out not to be captured
  anywhere else, move it into one of those two files first.
- Follow-ups to file as separate issues, not part of this plan: automatic
  rollback of a bad deploy; non-Fly deployment stacks; dataset extension code
  version-gating; **data migration across major versions (#88)**; a future
  "this update seems stuck" retry/warning heuristic (non-goals); a future
  filtering/policy feature for which update notifications get surfaced
  (non-goals) — if built, either would introduce its own new mechanism then,
  not resurrect `auto_update` or a CI write-back.
