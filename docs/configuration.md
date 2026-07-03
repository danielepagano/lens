# Lens project configuration

A **Lens project** is a Git repository with a `lens.toml` at its root, plus `knowledge/` and `narrative/` trees. Lens reads configuration from `lens.toml` and from **narrative node front matter** (YAML between `---` markers in `_node.md` and leaf `.md` files). Credentials are never stored in the repo: each backend names an environment variable via `api_key_env`.

This guide covers every supported configuration surface, environment variables, and validation (`lens check`). For command syntax see the [CLI reference](../lens/cli/README.md); for architecture see [Design](design.md); for hosting the UI/API see [Deployment](../deploy/README.md).

## Table of contents

1. [Project layout](#project-layout)
2. [`lens.toml` overview](#lenstoml-overview)
3. [`[project]`](#project)
4. [`[[llm]]`](#llm)
5. [`[operator.<name>]`](#operatorname)
6. [`[[image]]`](#image)
7. [`[[speech]]`](#speech)
8. [`[compress]`](#compress)
9. [`[params]`](#params)
10. [`[dataset]`](#dataset)
11. [`[release]` / `[[dataset_repo]]`](#release--dataset_repo)
12. [Narrative front matter](#narrative-front-matter)
13. [Prompt packs](#prompt-packs)
14. [Dataset bundles](#dataset-bundles)
15. [Environment variables](#environment-variables)
16. [Validation: `lens check`](#validation-lens-check)
17. [Precedence reference](#precedence-reference)

---

## Project layout

`lens init` (inside an existing Git repo) creates:

| Path | Purpose |
|------|---------|
| `lens.toml` | Project configuration |
| `knowledge/` | Project-local knowledge store (`{type}/{key}.md`, `tags.toml`) |
| `narrative/` | Narrative trees (`<slug>/_node.md`, child nodes as files or folders) |

Select the active narrative with `lens use <slug>`, which sets `[project].narrative` and creates `narrative/<slug>/_node.md` if needed.

---

## `lens.toml` overview

| Section | Required | Purpose |
|---------|----------|---------|
| `[project]` | Implicit (created by `lens init`) | Active narrative, datasets, media mount, locale, prompt pack |
| `[[llm]]` | For AI operators | OpenAI-compatible chat backends |
| `[operator.<name>]` | No | Per-operator LLM defaults |
| `[[image]]` | For `lens media generate` | Image generation backends |
| `[[speech]]` | For `lens media tts` | Text-to-speech backends |
| `[compress]` | No | Auto-compress size thresholds |
| `[params]` | No | Default operator invocation parameters |
| `[dataset]` | No | Dataset-level flags (e.g. verbose LLM logging) |
| `[release]` | No | Cloud release tracking policy (absent = disabled) |
| `[[dataset_repo]]` | No | External dataset repos to clone on the server volume |
| `[config-<name>]` | No | Dataset-specific configuration overrides (one section per loaded dataset) |

Array sections (`[[llm]]`, `[[image]]`, `[[speech]]`) use the **first entry as the default** unless you pass `--llm`, `--model`, or an explicit `id` in the API.

---

## `[project]`

```toml
[project]
narrative    = "my-campaign"      # active narrative slug (also set by `lens use`)
datasets     = ["rpg", "companion"] # dataset names; later entries shadow earlier
mount_point  = "media"            # optional: local path or s3:// URI
verbose_llm  = true               # log full prompts/responses at INFO
prompt_pack  = "default"          # optional: override bundled prompt templates
locale       = "en-US"            # BCP-47 tag for formatting (default en-US)
```

### `narrative`

Slug of the tree under `narrative/<slug>/`. Must match `^[a-zA-Z0-9_-]+$`. Updated by `lens use`.

### `datasets`

List of dataset **names** to merge (e.g. `rpg`, `companion`). Lens resolves each name to a directory — bundled under `datasets/<name>/` in the install, a **sibling folder** next to the Lens repo (`../<name>/`), or an explicit path in the project’s `lens.local.toml` `[dataset_paths]`. See **[datasets/README.md](../datasets/README.md)**.

Later names **shadow** earlier ones for KB objects; project-local knowledge always wins on write (copy-on-write).

Dataset-gated commands and operators (e.g. `play`, `advance`) only appear when the required dataset name is listed and resolves. Datasets with `[dataset] extension` in their `lens.toml` may add CLI groups and LLM command tools when listed (see [datasets/README.md](../datasets/README.md)).

### `mount_point`

Enables `lens media attach`, `lens media generate`, `lens media tts`, and the web UI media browser.

| Form | Example | Backend |
|------|---------|---------|
| Relative path | `"media"` | Directory under project root |
| Absolute path | `"/mnt/assets"` | Directory at that path |
| S3 URI | `"s3://my-bucket"` or `"s3://bucket/prefix"` | S3-compatible object storage |

**Local mounts:** Lens does not manage layout inside the mount; only mount-relative paths can be attached.

**S3 mounts:** Credentials from standard AWS env vars (see [Environment variables](#environment-variables)). The URI uses the **bucket name**, not the endpoint hostname:

```toml
# Correct
mount_point = "s3://lens/assets"

# Wrong — endpoint belongs in AWS_ENDPOINT_URL, not the URI
# mount_point = "s3://acct.r2.cloudflarestorage.com/lens/assets"
```

`lens media attach photo.jpg` resolves `photo.jpg` relative to the mount root. Presigned URLs in the web UI require an `s3://` mount.

### `verbose_llm`

When `true`, each LLM call logs `[SYSTEM]` / `[USER]` / `[ASSISTANT]` blocks at INFO (no raw SSE noise).

### `prompt_pack`

Name of a TOML file under `lens/prompts/` (e.g. `default` → `lens/prompts/default.toml`). Override operator system/instruction templates. Select with `lens prompt use-pack <name>` or set in TOML. `lens check` warns if the file is missing.

### `locale`

BCP-47 locale for project formatting defaults (default `en-US`).

---

## `[[llm]]`

At least one `[[llm]]` entry is required for AI operators (`write`, `edit`, `play`, `chat`, `design`, `compress`, etc.).

```toml
[[llm]]
base_url         = "https://api.openai.com/v1"
model            = "gpt-4o"
api_key_env      = "OPENAI_API_KEY"
temperature      = 0.8
first_token_timeout_seconds = 10
timeout_seconds  = 120
reasoning        = false
reasoning_effort = "medium"

[[llm]]
id               = "fast"
base_url         = "https://api.openai.com/v1"
model            = "gpt-4o-mini"
api_key_env      = "OPENAI_API_KEY"
```

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `base_url` | Yes | — | OpenAI-compatible API root (e.g. `https://api.openai.com/v1`, Ollama, proxies) |
| `model` | No | `""` | Model id sent in the request body when non-empty |
| `api_key_env` | No | — | Env var name for the API key; if set, variable must be present at runtime |
| `id` | No | — | Select with `--llm <id>`; first entry uses its `id` or `[default]` in listings |
| `temperature` | No | `0.8` | Sampling temperature |
| `first_token_timeout_seconds` | No | `10` | Wall-clock until HTTP headers + first SSE data line |
| `timeout_seconds` | No | `120` | Max idle between stream lines after the first line |
| `reasoning` | No | `false` | Enable provider “thinking” / reasoning mode for this entry |
| `reasoning_effort` | No | `"medium"` | When reasoning is on: `"low"`, `"medium"`, or `"high"` |

Any OpenAI-compatible `/chat/completions` endpoint works; set `base_url` to match the provider.

### Extra HTTP headers and body (`[llm.extra_headers]`, `[llm.extra_payload]`)

Vendor-specific extensions are passed through without Lens interpreting them. Attach subtables to the active `[[llm]]` row:

```toml
[[llm]]
base_url = "https://api.example.com/v1"
model = "my-model"
api_key_env = "MY_API_KEY"

[llm.extra_headers]
HTTP-Referer = "https://example.com"
X-Custom = "my-app"

[llm.extra_payload]
routing = { sort = "throughput", allow_fallbacks = false }
```

| Subtable | Semantics |
|----------|-----------|
| `[llm.extra_headers]` | String → string; merged into request headers |
| `[llm.extra_payload]` | Top-level JSON body fields; TOML values used as-is; **strings** parsed as JSON, then YAML |

String payload example:

```toml
[llm.extra_payload]
routing = '''
sort: throughput
order: [vendor-a, vendor-b]
'''
```

**Merge order at request time:** Lens builds the standard payload (`messages`, `temperature`, `stream`, `reasoning`, tools, …), then `payload.update(extra_payload)` so extras can override Lens fields (e.g. `temperature`). Headers: `Accept` + `extra_headers`, then `Authorization` from `api_key_env` (**always wins** over any `Authorization` in `extra_headers`).

Shallow merge only — nested objects are replaced as a whole.

---

## `[operator.<name>]`

Override LLM behaviour per operator. All keys optional.

```toml
[operator.write]
llm              = "fast"
temperature      = 0.9
reasoning        = true
reasoning_effort = "high"
timeout_seconds  = 60
first_token_timeout_seconds = 20

[operator.play]
llm = "creative"
timeout_seconds = 300
```

Supported operator names include: `write`, `edit`, `section`, `collate`, `design`, `play`, `advance`, `chat`, `compress`, `session`, `remember` (any slug that invokes the LLM).

**LLM id precedence:** explicit `--llm` / API `llm_id` > pinned `params.llm_id` > `[operator.<name>].llm` > first `[[llm]]` entry.

**Other fields:** for the resolved `[[llm]]` entry, `[operator.<name>]` overrides `temperature`, timeouts, `reasoning`, and `reasoning_effort` (operator wins over the `[[llm]]` row).

`extra_headers` / `extra_payload` are **not** overridable per operator (only on `[[llm]]`).

---

## `[[image]]`

Required for `lens media generate`. Also requires `[project].mount_point`. The **first** `[[image]]` block is the default unless `--model <id>` is passed.

### A2E example

```toml
[[image]]
api              = "a2e"
model            = "a2e"
api_key_env      = "A2E_TOKEN"
base_url         = "https://video.a2e.ai"
aspect_ratios    = ["1:1", "16:9", "9:16", "4:3", "3:4"]
sizes            = ["1k", "2k"]
max_prompt_chars = 2000
max_batch        = 8
timeout_seconds  = 300
```

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `api` | Yes | — | Backend id; supported: `a2e` |
| `model` | Yes | — | Provider model type (A2E: `a2e` or `seedream`) |
| `api_key_env` | Yes | — | Env var for API token |
| `aspect_ratios` | Yes | — | Non-empty list of allowed aspect ratios |
| `sizes` | Yes | — | Non-empty list of size categories |
| `id` | No | `[default]` | Select with `--model` |
| `base_url` | No | `https://video.a2e.ai` | A2E API base |
| `max_prompt_chars` | No | `2000` | Max resolved prompt length |
| `max_batch` | No | `8` | Max images per request |
| `timeout_seconds` | No | `300` | Polling / request timeout |

Unknown keys are stored in the descriptor `extra` map for forward compatibility.

### Generate workflow

```bash
lens media generate "a moonlit cliff, oil painting style" \
    --aspect 16:9 --size 1k --batch 4 --slug forest-scene
```

- Output: `<mount>/generated/<slug>/b_<n>.yaml` sidecar + `b_<n>_r_*.png`
- Reusing `--slug` appends batches (`b_2_…`, `b_3_…`)
- Prompts may include `@` KB mentions and `@var:` (see [CLI — prompt syntax](../lens/cli/README.md#prompt-syntax))

---

## `[[speech]]`

Required for `lens media tts`. Requires `[project].mount_point`. Cache path: `<mount>/tts-cache/<narrative>/…`.

Each block selects a **backend** (`api`) and, for LLM generation with TTS tags, a **grammar** id that must match the provider’s transcript-tag format.

### xAI example

```toml
[[speech]]
api              = "xai"
api_key_env      = "XAI_API_KEY"
grammar          = "xai"
default_voice    = "rex"
base_url         = "https://api.x.ai/v1"
max_text_chars   = 15000
timeout_seconds  = 120
```

### OpenRouter example

Uses the OpenAI-compatible speech endpoint ([OpenRouter TTS](https://openrouter.ai/docs/guides/overview/multimodal/tts)).

```toml
[[speech]]
id               = "or-tts"
api              = "openrouter"
api_key_env      = "OPENROUTER_API_KEY"
model            = "openai/gpt-4o-mini-tts-2025-12-15"
grammar          = "gemini"
default_voice    = "alloy"
base_url         = "https://openrouter.ai/api/v1"
response_format  = "mp3"
max_text_chars   = 15000
timeout_seconds  = 120
```

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `api` | Yes | — | `xai` or `openrouter` |
| `api_key_env` | Yes | — | Env var for API key |
| `id` | No | `[default]` | Select with `lens media tts --model` |
| `grammar` | No* | — | TTS tag grammar: `xai` or `gemini` (required for `speech_markup` modality; invalid ids fail at load) |
| `refine_llm_id` | No | — | LLM id for `workflow_refine` (speech markup); defaults to operator LLM when unset |
| `default_voice` | No | — | Voice when `--voice` omitted (xAI fallback: `eve`) |
| `base_url` | No | provider default | API root |
| `model` | Yes for `openrouter` | `""` | TTS model id (OpenRouter) |
| `max_text_chars` | No | `15000` | Text length cap |
| `timeout_seconds` | No | `120` | Request timeout |
| `response_format` | No | `mp3` | OpenRouter: `mp3` or `pcm` |
| `speed` | No | — | OpenRouter playback speed when supported |

\*Set `grammar` on the `[[speech]]` block you use with the **`speech_markup`** modality (see below).

### Speech markup modality (generation)

Opt in on a node (or ancestor) so inline operators add TTS control tags during `write` / `play` / `chat`:

```yaml
---
modalities:
  speech_markup: true
---
```

- Uses the **default** (first) `[[speech]]` block’s `grammar` for generation and refine. The grammar must match that block’s engine (e.g. `grammar = "gemini"` with an OpenRouter/Gemini TTS model). `lens media tts --model` selects which block is used for **playback** only; markup always follows the default block’s `grammar` today.
- Prompt text is in the project/pack (`speech.markup.generate`, `speech.markup.refine`, `speech.grammar.<id>.rules`) — not KB pins. Grammars registered in Python may optionally override the three markup template keys (`generate_prompt_key`, `refine_prompt_key`, `refine_system_prompt_key`); bundled `xai` and `gemini` use the defaults above.
- Independent from **`attributed_dialogue`** (blockquote formatting); both can be active.
- After generate, **`workflow_refine`** runs a separate minimal LLM call (refine prompt only — no KB or passage crawl) on eligible dialogue lines; speech markup uses JSON input/output.

### TTS playback

```bash
lens media tts /@cursor --voice eve --language en
lens media tts /chapter-1@42
lens media tts my-story/act-2@16:80
```

- Node address + optional `@N` or `@N:M` line slice (same rules as other commands)
- `--silent` — skip `ffplay` playback
- xAI voices: `eve`, `ara`, `rex`, `sal`, `leo`; OpenRouter voices depend on the chosen `model`

---

## `[compress]`

Controls **automatic compression** after successful `write`, `play`, or `chat` (CLI or HTTP). Lens measures **visible** UTF-8 bytes on the cursor node (markdown comment annotations stripped). When thresholds fire, an optional LLM `compress` pass may collate prose into a child section.

```toml
[compress]
auto_compress = true
sm   = 15000
m    = 40000
l    = 80000
xl   = 150000
unit = "bytes"
```

| Field | Default | Description |
|-------|---------|-------------|
| `auto_compress` | `true` | Enable auto-compress after inline ops |
| `sm` | `15000` | Min growth delta (~3k tokens) to trigger between compressions |
| `m` | `40000` | Below this size, never auto-trigger |
| `l` | `80000` | TOML key `l` — medium aggressiveness band upper bound |
| `xl` | `150000` | Above this, high aggressiveness (must act) |
| `unit` | `"bytes"` | Only `"bytes"` is valid today |

Per-node override in front matter (see [Narrative front matter](#narrative-front-matter)). `compress.last_size` is written by Lens after a successful collate — do not edit manually.

Manual: `lens compress` / `lens collate` / structure-compress in the UI. See [Design — compression](design.md) for workflow and rollback behaviour.

---

## `[params]`

Default **operator invocation** parameters when CLI/API omit them. Structure:

```toml
[params]
[params.global]
llm_id = "fast"
reasoning = true

[params.chat]
as_kb_id = "npc.bob"
with_kb_id = "pc.amy"
narrate = true
wait = false
```

| Scope | Applies when |
|-------|----------------|
| `params.global` | Every operator |
| `params.<slug>` | Only that operator (`chat`, `write`, `play`, …) |

Use **canonical** keys (same as annotations / `extra_params`): `llm_id`, `reasoning`, `as_kb_id`, `with_kb_id`, `narrate`, `wait`, `as_pc`, `pass`, etc.

**Inheritance:** `lens.toml` `[params]` first, then each narrative ancestor **root → cursor**; deeper nodes win. **Invocation always wins** over pins (CLI flags, API body, `extra_params`).

**Chat sessions:** if the cursor is inside an open chat session and the caller does not pass `as_kb_id` / `with_kb_id`, pinned character ids are ignored so the session annotation defines speakers.

Edit via `lens pin param` / `lens pin var` (see CLI reference).

---

## `[dataset]`

Optional top-level section for dataset-scoped project flags:

```toml
[dataset]
verbose_llm = true
```

Currently used with the same effect as `[project].verbose_llm` for LLM logging (either can enable verbose prompts).

---

## `[config-<name>]` (dataset configuration)

A project may override configuration values exposed by a loaded dataset.  Each dataset defines its own set of keys and defaults in Python; the project can selectively override them under a `[config-<name>]` section where `<name>` matches the dataset name in `[project] datasets`.

```toml
[project]
datasets = ["rpg"]

[config-rpg]
# keys depend on the dataset — see that dataset's README
```

Keys not listed in the dataset's defaults are silently ignored.  See individual dataset READMEs (e.g. [`datasets/rpg/README.md`](../datasets/rpg/README.md)) for available keys.

---

## `[release]` / `[[dataset_repo]]`

Controls the **cloud release system**: auto-update policy, Lens version tracking,
and external dataset repos cloned onto the server volume.

The release system is **disabled** when `[release]` is absent from `lens.toml` —
all release CLI commands and server routes return a clear "not enabled" message.
Add the section to opt in.

```toml
[release]
enabled             = true
lens_repo_url       = "https://github.com/your-org/lens.git"
auto_update         = "minor"
requested_version   = ""
data_major_version  = 1
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `enabled` | No | `false` | Enable the release system for this project |
| `lens_repo_url` | Yes when enabled | `""` | SSH or HTTPS git URL of the Lens fork to track for version updates |
| `auto_update` | No | `"off"` | Auto-update policy: `"off"`, `"minor"`, or `"major"` |
| `requested_version` | No | `""` | Explicit version to target (e.g. `"v2.1.0"`); cleared once fulfilled |
| `data_major_version` | No | `1` | Major version the project's data is compatible with; bumped by migration |
| `migration_pending` | No | `false` | Set by CI when a migration commit is pending approval |
| `migration_target_version` | No | `""` | Target version of the pending migration |
| `migration_commit` | No | `""` | Git commit SHA of the pending migration commit |

`migration_pending`, `migration_target_version`, and `migration_commit` are
system-managed — Lens sets them during the migrate workflow.  Do not edit them
manually.

### `[[dataset_repo]]`

External dataset repos that are cloned onto the server volume (Fly) for
runtime use, not baked into the Docker image.  Each entry is fetched and
fast-forwarded independently during refresh.

```toml
[[dataset_repo]]
name    = "lens-dnd"
git_url = "git@gitlab.com:org/lens-dnd.git"
ref     = "main"

[[dataset_repo]]
name    = "custom-rules"
git_url = "https://github.com/org/custom-rules.git"
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | — | Matches an entry in `[project].datasets`; `lens check` warns if it does not |
| `git_url` | Yes | — | SSH or HTTPS git URL of the dataset repository |
| `ref` | No | `"main"` | Git ref (branch, tag, or commit) to track |

`lens check` validates each repo's `git_url` format and warns when `name`
does not match any entry in `[project] datasets`.

---

## Narrative front matter

YAML at the top of node files (`---` … `---`). Not in `lens.toml` but central to behaviour.

### Knowledge pins

| Key | Purpose |
|-----|---------|
| `kb_pin` | KB ids included in crawl context (ancestor chain, root → cursor) |
| `kb_unpin` | Cancel an ancestor pin for this subtree |

Manage with `lens pin kb add|remove|block|unblock`. The `+` suffix on an id expands linked objects (shared dot-tags).

### `vars`

String substitution in prompts (`@var:key`). **Node front matter only** — not in `lens.toml`.

```yaml
vars:
  mood: tense
  season: winter
```

Inherited root → cursor; deeper overrides.

### `params`

Same structure as `[params]` in TOML (`global` + per-operator slugs). Merged with `lens.toml` and ancestors.

### `compress`

```yaml
compress:
  auto_compress: false
```

Overrides project `[compress].auto_compress` for this node. `compress.last_size` is system-managed.

---

## Prompt packs

Bundled under `lens/prompts/*.toml`. Each file has a `[prompts]` table of template strings (keys like `write.system`, `play.instruction_continue`). Variables use `{name}` placeholders.

Set `[project].prompt_pack` or run `lens prompt use-pack <name>`. Operators resolve templates through `PromptStore` with dataset and pack overrides.

---

## Dataset bundles

Declared in `[project].datasets`. Full guide (authoring, sibling layout, `lens.local.toml`, CLI from a dataset folder): **[datasets/README.md](../datasets/README.md)**.

| Name | In this repo? | Purpose |
|------|----------------|---------|
| `rpg` | Yes (`datasets/rpg/`) | `play`, `advance`, rules, templates — [rpg/README.md](../datasets/rpg/README.md) |
| `companion` | Yes (`datasets/companion/`) | Companion chat, memory — [companion/README.md](../datasets/companion/README.md) |
| `testing` | Yes (tests only) | Minimal fixtures |
| *your name* | No — your repo | private sibling folder or `[dataset_paths]`; not distributed with Lens |

Project KB edits to a dataset object create a local copy. Import bulk markdown with `lens kb extract` where supported.

---

## Environment variables

### LLM / image / speech

| Variable | When |
|----------|------|
| Names in `api_key_env` | Required at runtime when the field is set on `[[llm]]`, `[[image]]`, or `[[speech]]` |

### S3 mount (`mount_point = "s3://…"`)

| Variable | Purpose |
|----------|---------|
| `AWS_ACCESS_KEY_ID` | Credentials |
| `AWS_SECRET_ACCESS_KEY` | Credentials |
| `AWS_ENDPOINT_URL` | S3-compatible endpoint (R2, MinIO, …) |
| `AWS_DEFAULT_REGION` | Region |

### Development / testing

| Variable | Purpose |
|----------|------|
| `LENS_DEV_SERVER_URL` | E2E / tests: target a running dev server instead of starting uvicorn |

### Deployment

Hosting (Fly.io, secrets, Caddy): see **[deploy/README.md](../deploy/README.md)** only. `lens deploy init` / `lens deploy push` read `api_key_env` values from your shell into Fly secrets when you deploy.

| Variable | Purpose |
|----------|---------|
| `LENS_CLOUD_DEPLOYED` | Set to `1` on Fly by `lens deploy init`; runtime requires `s3://` when `mount_point` is configured (local paths are rejected) |
| `LENS_PROJECT_DIR` | Clone root on the server volume |
| `LENS_PROJECT_SLUGS` | Comma-separated slugs for multi-project apps |
| `LENS_PORT` | API port behind Caddy |

---

## Validation: `lens check`

```bash
lens check
lens check --skip-network
```

| Check | Level |
|-------|-------|
| `lens.toml` exists | error |
| Each `[[llm]]` has `base_url` | error |
| LLM endpoint TCP reachable | error (skipped with `--skip-network`) |
| `api_key_env` set in environment | error when configured |
| `mount_point` local path exists | error |
| `mount_point` s3:// + AWS env vars | error / ok |
| `prompt_pack` file exists | warn if missing |
| Each `datasets` name has bundled dir | warn if missing |
| Active `narrative` folder exists | warn if missing |
| `[release]` configuration | ok / error | if present: `lens_repo_url` format, `auto_update` values, `data_major_version` |
| `[[dataset_repo]]` entries | error / warn | if present: valid `git_url`, `name` matches `[project] datasets` |

Image and speech backends are not fully probed here; missing keys surface when you run `lens media`.

---

## Precedence reference

### LLM selection

1. CLI `--llm` / API `llm_id`
2. Pinned `params.*.llm_id` (merged params)
3. `[operator.<name>].llm`
4. First `[[llm]]` entry

### LLM tunables (temperature, timeouts, reasoning)

For the **resolved** `[[llm]]` row: `[operator.<name>]` > `[[llm]]` entry > built-in defaults.

### HTTP extras

`[[llm]].extra_headers` / `extra_payload` only (no operator override). Payload extras applied after Lens fields; `Authorization` always from `api_key_env` last.

### Operator params (`params`)

1. Invocation (CLI/API/`extra_params`)
2. Merged pins: `lens.toml` → ancestors root→cursor (deeper wins); per-slug overrides `global`

### Knowledge crawl

Ancestor `kb_pin` / `kb_unpin` root→cursor; runtime `--pin` / `--unpin` and `@type.key` mentions add to the crawl for that call.

---

## Related documentation

- [CLI reference](../lens/cli/README.md) — commands and flags
- [Web UI & API](../lens/server/README.md) — HTTP routes and frontend
- [Deployment](../deploy/README.md) — hosting the UI/API
- [Testing](testing.md) — fake LLM, e2e, bench
