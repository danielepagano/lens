# Lens Visuals - Design

> What is it: a refresh of the media system (carousel-based browser/manager) and the first
> image-generation pipeline for Lens, with a pluggable backend registry modeled on `[[llm]]`.

## Goals

- Replace the current one-off `/media` flow with a single carousel UI that powers attach,
  management, and generation review.
- Add image generation as a pluggable subsystem, delivered over SSE from the start (image
  backends vary wildly in latency — batches and local models can take minutes — and we already
  stream operators, so there's no reason to ever run generate synchronously).
- Introduce `media-visualize` — an LLM-assisted prompt-crafter that outputs a ready-to-run
  `media-generate` command, letting users compose and refine an image prompt from narrative
  context before committing to generation.
- Group all media commands under a `media-*` prefix (`media-attach`, `media-manage`,
  `media-generate`, `media-visualize`) so they appear together in CLI suggestions, the same way
  related command families group in the existing CLI.
- Keep Lens's invariants: the mount is the source of truth for assets, narrative changes go
  through the transactional storage layer, no git terminology in the UI, `core/` holds all
  business logic.

## Non-goals (for this ship)

- Audio/video generation.
- In-browser image editing (crop, paint, inpaint, etc.) — future phase / backlog.
- Server-side queue or job history. One generation at a time per project, reusing the existing
  `app.state.stream_lock` that operators already use.
- Multi-user / cross-session collaboration on generation sessions.
- Thumbnails — moved to future work.
- Reference images for generation — future phase.
- Multiple image API backends — one backend ships first; others added incrementally.

## Architectural pillars

### 1. Mount is the source of truth

All finalized assets — uploaded or kept from generation — live in the mount (local FS or
S3-compatible, typically R2). No separate DB, no new storage layer. A generation "session" is a
folder under the mount (`generated/<session-slug-or-id>/`) containing candidates plus a sidecar
`.lens-gen.json` describing prompt/model/settings. `media-manage` and `media-attach` treat these
folders like any other.

Generated images are ephemeral byte-streams until the user explicitly keeps them in the carousel
preview. Discard = delete from the session folder; nothing enters the repo until the user attaches
an image via `media-attach`.

### 2. Carousel is the only media UI

A single component, `MediaCarousel.svelte`, owns browse/spotlight/actions: thumbnail strip + large
spotlight + breadcrumb + action row (full-size view, folder nav, upload, download, rename/move,
delete, keep/discard for generation candidates). It opens after any `media-*` command that
produces output.

Two modes, driven by a `mode` prop:

- `attach` — adds a "Attach after…" CTA (the only way a mount file enters a narrative node).
- `manage` — same as attach minus the attach CTA; used after `media-generate` for browsing and
  keeping/discarding candidates. Delete lives in the carousel action row — there is no separate
  "remove media" command.

No dialogs. Every generation is initiated from a CLI command. The carousel is the output view,
not an input form.

**Retry**: when the user wants to retry a generation, the carousel surfaces a "Retry" action that
re-populates the original `media-generate` command in the CLI input, reconstructed from in-memory
carousel state or the session `.lens-gen.json` sidecar — so no state is lost between attempts.

Command-to-mode mapping:

| Command | Carousel mode |
|---|---|
| `media-attach` | `attach` |
| `media-manage` | `manage` |
| `media-generate` | `manage` (session folder, SSE-populated as results land) |
| `media-visualize` | none — emits a `media-generate` command; user reviews and runs it |

This collapses the current `features/cli/Media*Panel.svelte` files into one `features/media/`
folder and removes the old `/media <action>` surface.

### 3. media-* command group

All media commands share the `media-` prefix so they appear grouped in CLI autocomplete and
help output. There is no standalone `/manage`, `/attach`, or "remove media" command.

**`media-attach`** — open carousel in attach mode; optionally scoped to a subfolder.

**`media-manage`** — open carousel in manage mode for browsing and housekeeping.

**`media-generate [prompt] [--model <id>] [--aspect <ratio>] [--size <cat>] [--batch <n>]
[--slug <name>]`** — start a generation session and stream results into the carousel. `--slug`
names the session folder (`generated/<slug>/`); if omitted, a short auto-generated ID is used. A
slug can be reused to resume reviewing an existing session.

**`media-visualize [meta-prompt] [--slug <name>]`** — craft an image prompt via LLM and output a
ready-to-run `media-generate` command with the `--slug` forwarded. No automatic dispatch; the user
reviews, edits if needed, and runs the command.

### 4. Pluggable image backends

Mirror the LLM config shape. In `lens.toml`:

```toml
[[image]]
id = "flux-pro"
api = "openrouter"                      # openrouter | a2e | ...
model = "black-forest-labs/flux-1.1-pro"
api_key_env = "OPENROUTER_API_KEY"
aspect_ratios = ["1:1", "16:9", "9:16", "4:3", "3:4"]
sizes = ["1k", "2k"]
# Hard cap on resolved prompt length. Enforced server-side before dispatch and again
# after @-mention expansion. Server rejects (does not truncate) if exceeded.
max_prompt_chars = 2000
```

Core abstraction:

```
lens/core/image/
  spec.py       # ImageSpec dataclass (prompt, negative, aspect, size, batch, model_id)
  backend.py    # ImageBackend ABC: async generate(spec) -> AsyncIterator[ImageEvent]
                # ImageEvent union: Progress(phase, pct?, message?),
                # ItemReady(index, bytes, ext, metadata), Done, Error.
                # Backends that can't stream incremental items still emit
                # Progress heartbeats and a single ItemReady per result.
  openrouter.py # implements ImageBackend for OpenRouter multimodal
  registry.py   # reads [[image]] blocks, returns (descriptor, backend) for a model id
```

The `AsyncIterator` contract means the route handler streams events out over SSE without ever
holding the whole batch in memory, and slow providers look the same to the UI as fast cloud ones —
there is always a heartbeat.

### 5. Prompt length enforcement

`max_prompt_chars` is enforced server-side in two passes: once against the raw prompt and once
after `@`-mention resolution (since expansions can push the resolved prompt well past the cap).
The server **rejects** over-length prompts with a descriptive error — it never truncates silently.
The UI surfaces the error inline in the CLI output area; the user must edit the prompt and retry.
This applies equally to `media-generate` and to the crafted prompt emitted by `media-visualize`.

### 6. @-mentions replace, not append

Inside generation prompts, `@type.key` tokens are resolved inline — the KB body replaces the
token. This lets users compose prompt snippets using the KB system. It diverges from how pins
work (pins append into the prompt context), and that's intentional: an image prompt is a single
string, not a context window.

Implementation note: the existing KB mention parser in `core/command_tools.py` already handles
tokenization. Factor out a small `resolve_mentions(text, kb, *, strategy="replace"|"append")`
helper; `media-generate` / `media-visualize` call it with `replace`. Expansion suffix (`+`) is
supported.

## Phased plan

Each phase is shippable and independently testable. Later phases build on the earlier ones without
touching them.

### Phase 1 — Carousel UI + media-attach

Goal: land the new media UX with feature parity over today's flows, plus rename/move and
upload-during-browse. No generation yet.

**Backend**
- `MountBackend.move(src, dst)` on all backends (S3 = copy+delete). Route
  `PATCH /{project}/mount/file/{path}` with `{to: <new path>}`.
- `api.ts` additions: `moveMountFile`.

**Frontend**
- New `features/media/` folder containing `MediaCarousel.svelte` + sub-components
  (`MediaStrip.svelte`, `MediaSpotlight.svelte`) as needed to stay under the 300-line cap.
- `media-attach` and `media-manage` commands backed by the carousel. Upload is an inline
  affordance within the carousel (drag-drop or file picker in the action row) — no separate upload
  panel.
- Remove `features/cli/Media*Panel.svelte`. Hard-remove `/media <action>` (internal tool, small
  blast radius, no deprecation period needed).

**DoD**
- Unit: `move()` on both mount backends (existing test pattern).
- E2E: open `media-attach`, paginate folders, upload during browse, rename, delete, attach after a
  specific line.
- `poe check` green.

### Phase 2 — media-generate with a single backend

Goal: prove the generation pipeline end-to-end with one backend (OpenRouter multimodal).
Deliberately narrow: no references, no extras, one backend.

**Backend**
- `lens/core/image/` as described. Only `openrouter.py` implemented; `a2e.py` as a stub file
  (raises `NotImplementedError`) to exercise the registry shape from day one.
- `lens/core/commands/generate.py`:
  1. Resolve `@kb.id` tokens (replace strategy). Enforce `max_prompt_chars` before and after
     resolution; reject with error if exceeded.
  2. Build `ImageSpec` from request (prompt, aspect, size, batch, model_id).
  3. Accept optional `slug`; derive session folder as `generated/<slug-or-id>/`.
  4. Dispatch via registry. Write each result to `<mount>/generated/<slug>/<n>.<ext>` and write
     `.lens-gen.json` sidecar (prompt, resolved prompt, model, settings).
- Route: `POST /{project}/generate` → `text/event-stream`. Acquires `app.state.stream_lock`.
  Events: `progress`, `item`, `done`, `error`. `item` payloads carry `{index, path}` so the
  carousel can light up each tile as it lands.
- `GET /{project}/image/models` returns model descriptors.
- `lens/testing/fake_image.py` — fake backend emitting 1×1 PNGs and echoing the resolved prompt
  + settings in the sidecar. Mirrors `FakeLLMServer`.

**Frontend**
- `media-generate` CLI command: prompt text + flags (`--model`, `--aspect`, `--size`, `--batch`,
  `--slug`). On submit, open carousel in `manage` mode rooted at the session folder; SSE events
  populate tiles as they arrive; `error` (including prompt-too-long) surfaces inline in the CLI
  output area.
- Carousel "Retry" action: re-populates `media-generate` in the CLI from in-memory state or the
  `.lens-gen.json` sidecar.
- SSE plumbing lives only in `services/sse.ts` (existing), matching the frontend contract.

**DoD**
- Unit: mention resolver (replace strategy).
- Unit: `generate` core with fake backend writes N files + sidecar.
- Unit: registry loads multiple `[[image]]` blocks and picks by id.
- Unit: prompt-too-long rejected before and after mention resolution.
- E2E: `media-generate`, candidates appear in carousel, discard/keep, attach one via
  `media-attach`.
- `poe check` green.

### Phase 3 — media-visualize

Goal: LLM-authored image prompts as a precursor to `media-generate`.

`media-visualize [meta-prompt] [--slug <name>]` runs an operator that:
1. Crawls context using the standard crawl (inherits all pin semantics, including node-slice pins —
   this is what allows visualizing an ongoing scene by pulling character appearance, location,
   mood, etc. from the current narrative position).
2. Feeds meta-prompt + crawl to the LLM with a system prompt that specializes it as an
   image-prompt author (dense visual language, no prose, respect style tokens).
3. Outputs the crafted prompt to the CLI output area as a ready-to-run `media-generate` command
   (e.g. `media-generate "a moonlit cliff, dramatic shadows, oil painting style" --slug
   forest-scene`), with `--slug` forwarded if provided.
4. The user reviews, edits if needed, and runs the emitted command. No dialog; no automatic
   dispatch.

`lens/core/operators/visualize.py` implements this. The sidecar written by the subsequent
`media-generate` call stores both meta-prompt and crafted-prompt for traceability.

**DoD**
- Operator test with a fake LLM: meta-prompt + two pins yields a crafted prompt containing
  expected tokens, emitted as a valid `media-generate` command string.
- E2E: `media-visualize`, review emitted command, run it, land in carousel on the session folder.
- `poe check` green.

## Future work

- **Thumbnails**: install ffmpeg on the server; generate a `_tb` file alongside each upload for
  fast strip rendering. No Cloudflare Images dependency needed — keeps dev and self-hosted setups
  simple with zero external accounts required.
- **Reference images**: `ImageSpec.references: list[str]` (mount paths). `media-generate --ref
  <mount-path>`. Introduces a `pick` mode on the carousel (third mode) that returns a path to the
  caller. Backends without support surface a clear error.
- **Additional backends**: A2E and others. Same `ImageBackend` ABC. Add a "Adding a new image
  backend" section to this doc once the second backend lands.
- **Old session cleanup**: no sweeper in v1; users clean up via `media-manage`. Revisit if mounts
  grow large.
- **Image ops** (`remove_background`, `upscale`, `img2img`, `inpaint`): `ImageOp` as a sibling of
  `ImageSpec`, routed through `POST /{project}/image/ops/{op_id}`. Carousel acts as both input
  picker and output viewer.

## Cross-cutting concerns

### Transactions

The mount is outside git, so generations and renames/moves do **not** create a Lens transaction.
Attaching a generated image into a narrative node does — that remains the existing `attach` flow.
This preserves the single-pending-transaction invariant without special cases.

### Sidecar durability

`.lens-gen.json` is informational — never load-bearing. A missing/corrupt sidecar must not break
anything; the image is still just an image. `media-manage` and `media-attach` use it only to
surface "prompt used" metadata in the spotlight and to reconstruct the `media-generate` command
for carousel retry.

### Security / cost controls

- `[[image]]` uses `api_key_env` (never in `lens.toml`). Same pattern as `[[llm]]`.
- `max_prompt_chars` is enforced server-side before dispatch and re-checked after mention
  resolution. The server **rejects** (does not truncate) with a descriptive error; the UI surfaces
  it inline and the user must edit and retry.
- Only one generation runs at a time per project (`app.state.stream_lock`), preventing runaway
  cost from double-firing.
- Generated images are ephemeral byte-streams in the session folder until the user explicitly
  keeps them in the carousel preview. Nothing enters the repo until the user attaches an image via
  `media-attach`.

### UI contracts

- All carousel components live under `features/media/` and respect the frontend CLAUDE.md rules
  (≤300 lines per component, no network in components, no layout redefinition, address paths
  always).
- No git terminology. "Keep" and "Discard" in the carousel, not "Commit" / "Revert".
- No dialogs for generation or visualization — those are CLI commands; the carousel is the
  post-command output view only.
- On 401, the existing fatal-401 behavior applies unchanged.

## Open questions

1. **Old session cleanup**: no sweeper in v1. Users clean up via `media-manage`. Revisit if mounts
   get large.
