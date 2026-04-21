# Lens Visuals - Design

> What is it: a refresh of the media system (carousel-based browser/manager) and the first
> image-generation pipeline for Lens, with a pluggable backend registry modeled on `[[llm]]`.

## Goals

- Replace the current one-off `/media` flow with a single carousel UI that powers attach, manage,
  reference-picking, and generation review.
- Ship thumbnails via Cloudflare Images (R2 is already the store) with a clean fallback so dev and
  self-hosted setups work without CF.
- Add image generation as a pluggable subsystem. Two initial API families
  (OpenRouter multimodal, A2E), with models declared in `lens.toml`. Other APIs / models added
  incrementally.
- Introduce `/visualize` — an LLM-assisted prompt-crafter on top of `/generate` that leverages the
  pin system (including node-slice pins) to visualize ongoing scenes using the knowledge we already
  track.
- Keep Lens's invariants: the mount is the source of truth for assets, narrative changes go through
  the transactional storage layer, no git terminology in the UI, `core/` holds all business logic.

## Non-goals (for this ship)

- Audio/video generation.
- In-browser image editing (crop, paint, inpaint, etc.) — future phase / backlog.
- Server-side queue or job history. Generation is synchronous per call for v1.
- Multi-user / cross-session collaboration on generation sessions.

## Architectural pillars

### 1. Mount is the source of truth

All finalized assets — uploaded or generated — live in the mount (local FS or S3-compatible,
typically R2). No separate DB, no new storage layer. A generation "session" is simply a folder
under the mount (`generated/<session-id>/`) containing candidates plus an optional sidecar
`.lens-gen.json` describing prompt/model/settings. `manage` and `attach` can treat these folders
like any other, so the carousel is the only affordance users need to learn.

### 2. Carousel is the only media UI

Today we have three ad-hoc dialogs (`MediaPreviewPanel`, `MediaUploadPanel`, `MediaRemovePanel`)
and a `/media <action>` command. The new model:

- One component, `MediaCarousel.svelte`, owns browse/spotlight/actions:
  thumbnail strip + large spotlight + breadcrumb + action row (full-size view, folder nav, upload,
  download, rename/move, delete). Thumbnails request `/mount/thumb/...`; spotlight requests
  `/mount/file/...`.
- Three modes, driven by a `mode` prop:
  - `attach` — adds a CTA "Attach after…" (this is the only way a mount file enters a node).
  - `manage` — same as attach minus the attach CTA.
  - `pick` — a resolver mode; returns a mount path to the caller (used by generate for reference
    images, and later by other ops). No mutation affordance beyond navigation.
- All three map to commands: `/attach`, `/manage`, and an internal "pick" opened programmatically
  from generate/visualize.

This collapses the current feature-cli/Media\* files into one feature folder and removes the
`/media <action>` surface.

### 3. Pluggable image backends

Mirror the LLM config shape. In `lens.toml`:

```toml
[[image]]
id = "flux-pro"
api = "openrouter"                      # openrouter | a2e | ...
model = "black-forest-labs/flux-1.1-pro"
api_key_env = "OPENROUTER_API_KEY"
aspect_ratios = ["1:1", "16:9", "9:16", "4:3", "3:4"]
sizes = ["1k", "2k"]
supports_reference = true
# optional, rendered as form controls in the Generate dialog
[[image.extras]]
name = "guidance"
type = "float"
default = 3.5
min = 1.0
max = 10.0
```

Core abstraction:

```
lens/core/image/
  spec.py       # ImageSpec dataclass (prompt, negative, aspect, size, batch,
                # model_id, references: list[str], extras: dict)
  backend.py    # ImageBackend ABC: generate(spec) -> list[ImageResult]
                # ImageResult carries bytes + suggested ext + per-item metadata
  openrouter.py # implements ImageBackend for OpenRouter multimodal
  a2e.py        # implements ImageBackend for A2E
  registry.py   # reads [[image]] blocks, returns (descriptor, backend) for a model id
```

Registry descriptor includes capability flags (`supports_reference`, `aspect_ratios`, `sizes`,
`extras_schema`) so the Generate dialog can render only the fields the active model supports.

### 4. Thumbnails via Cloudflare Images, with fallback

New route `/{project}/mount/thumb/{path:path}?variant=small|medium|large`.

- If `[mount] cf_images_base = "https://imagedelivery.net/<account>/..."` is configured in
  `lens.toml` and the underlying backend is S3/R2 with a public URL format, the route returns a
  302 to the CDN URL at the right variant.
- Otherwise the route streams the original bytes (local dev, small self-hosts). The frontend
  doesn't care — it always hits `/mount/thumb/...` and lets the server decide.

Variants map to UI needs:
- `small` — strip thumbnail (~160px)
- `medium` — spotlight on small screens
- `large` — spotlight full-size

### 5. @-mentions replace, not append

Inside generation/visualize prompts, `@type.key` tokens are resolved inline — the KB body replaces
the token. This lets users compose prompt snippets using the KB system. It diverges from how pins
work (pins append into the prompt context), and that's intentional: an image prompt is a single
string, not a context window.

Implementation note: the existing KB mention parser in `core/command_tools.py` already handles the
tokenization. Factor out a small `resolve_mentions(text, kb, *, strategy="replace"|"append")`
helper; `generate` / `visualize` call it with `replace`. Expansion suffix (`+`) is supported.

## Phased plan

Each phase is shippable and independently testable. Later phases build on the earlier ones without
touching them.

### Phase 1 — Carousel UI + thumbnail pipeline (no generation yet)

Goal: land the new media UX with feature parity over today's flows, plus rename/move and thumbs.

**Backend**
- `MountBackend.move(src, dst)` on all backends (S3 = copy+delete). Route
  `PATCH /{project}/mount/file/{path}` with `{to: <new path>}`.
- `/{project}/mount/thumb/{path}` route. `[mount] cf_images_base` config. When unset, stream the
  original (zero regression).
- `api.ts` additions: `moveMountFile`, `getMountThumbPath(path, variant)`.

**Frontend**
- New `features/media/` folder containing `MediaCarousel.svelte` + thin wrappers for the three
  modes. Remove `features/cli/Media*Panel.svelte`.
- New commands `/attach` and `/manage`; `/media` hard-removed (no deprecation period — internal
  tool, small blast radius).
- Keep `MediaCarousel` under the 300-line cap by extracting `MediaStrip.svelte` and
  `MediaSpotlight.svelte` if needed.

**DoD**
- Unit: thumbnail route returns 302 when CF configured, streams bytes when not.
- Unit: `move()` on both mount backends (existing test pattern).
- E2E: open `/attach`, paginate folders, upload, rename, delete, attach after a specific line.
- `poe check` green.

### Phase 2 — `/generate` with a single backend, no references

Goal: prove the pipeline end-to-end with OpenRouter multimodal. Deliberately narrow.

**Backend**
- `lens/core/image/` as described above. Only `openrouter.py`. `a2e.py` lives as a stub file that
  raises `NotImplementedError` so the registry shape is exercised from day one.
- `lens/core/commands/generate.py`:
  1. Resolve `@kb.id` tokens in the prompt (replace strategy).
  2. Build `ImageSpec` from request.
  3. Dispatch via registry. On success, write each result to
     `<mount>/generated/<session-id>/<n>.<ext>` and write `.lens-gen.json` sidecar.
  4. Return `{session_id, paths, prompt_resolved}`.
- Route: `POST /{project}/generate`. Synchronous. Per-request caps (`max_batch`, `max_size`) read
  from the `[[image]]` entry and enforced before dispatch.
- New route `GET /{project}/image/models` returning descriptors for the Generate dialog.
- `lens/testing/fake_image.py` — drop-in fake backend emitting 1x1 PNGs and echoing the resolved
  prompt + settings in the sidecar. Mirrors `FakeLLMServer`.

**Frontend**
- `features/media/GenerateDialog.svelte` — prompt textarea with KB @-mention autocomplete, model
  picker, aspect ratio, size category, batch size, and dynamic extras (driven by
  `extras_schema`).
- On submit: show progress, then open the carousel in `manage` mode rooted at the session folder.

**DoD**
- Unit: mention resolver (replace strategy), `generate` core with fake backend writes N files +
  sidecar.
- Unit: registry loads multiple `[[image]]` blocks and picks by id.
- E2E: `/generate`, candidates appear in carousel, delete/keep, attach one via `/attach`.

### Phase 3 — Reference images + picker mode

Goal: add the parts that require UI ↔ mount interplay.

- `ImageSpec.references: list[str]` (mount paths). Backends missing support raise
  `ImageSpec.Unsupported`; the dialog hides the field based on capability flags.
- `GenerateDialog` adds a "Reference images" row. "Add reference" opens `MediaCarousel` in
  `pick` mode; selection returns a path back to the dialog.
- OpenRouter encoder forwards references as image URLs (served from the mount via a short-lived
  signed URL for S3/R2, or directly via `/mount/file/...` for local).

**DoD**
- Carousel `pick` mode unit test (emits path, no mutation).
- Integration: generate with two references round-trips through the fake backend.

### Phase 4 — Second backend (A2E) + richer extras

Goal: prove the abstraction with a second real backend and the `extras_schema` pattern.

- Implement `a2e.py`. Map its specific knobs into `extras_schema` entries. Where semantics don't
  fit the common `ImageSpec` fields (e.g. A2E-specific sampler names), they go in `extras`.
- VCR-style fixture (or fake HTTP server in `lens/testing/`) for smoke tests of both backends.
- Short "Adding a new image backend" section appended to this doc once the second one lands.

**DoD**
- Unit: A2E backend dispatch encoding is covered.
- Unit: extras_schema renders expected form controls.

### Phase 5 — `/visualize` (LLM-authored image prompts)

Goal: take the user's meta-prompt + pins and produce an editable image prompt.

- New `lens/core/operators/visualize.py`. Reuses the standard context crawl so it inherits all pin
  semantics, including **node-slice pins** — this is what allows visualizing an ongoing scene by
  pulling character appearance, location, mood, etc. from the current narrative position.
- System prompt specializes the LLM as an image-prompt author (dense visual language, no prose,
  respect style tokens, etc.). Input: meta-prompt + crawl. Output: a prompt string.
- New `features/media/VisualizeDialog.svelte`: two-step.
  1. User enters meta-prompt + chooses pins/mentions as usual, submits.
  2. Editable textarea shows the crafted prompt; user edits and confirms, which hands off to the
     existing `/generate` pipeline (same dialog state for model/aspect/size/batch/references).
- Sidecar JSON stores both meta-prompt and crafted-prompt so iterations are traceable.

**DoD**
- Operator test with a fake LLM: meta-prompt + two pins yields a prompt containing expected
  tokens.
- E2E: `/visualize`, edit crafted prompt, submit, land in carousel on the session folder.

### Phase 6 — Future ops (backlog only, shape-compatible)

Not in this ship; noted to keep phases 2–4 forward-compatible.

- `remove_background`, `upscale`, `img2img`, `inpaint`, etc. Same backend abstraction
  (`ImageOp` as a sibling of `ImageSpec`), routed through `POST /{project}/image/ops/{op_id}`.
  Carousel acts as both input picker (`pick` mode) and output viewer (`manage` mode on the op's
  session folder).

## Cross-cutting concerns

### Transactions

The mount is outside git, so generations and renames/moves do **not** create a Lens transaction.
Attaching a generated image into a narrative node does — that remains the existing `attach` flow.
This preserves the single-pending-transaction invariant without special cases.

### Sidecar durability

`.lens-gen.json` is informational — never load-bearing. A missing/corrupt sidecar must not break
anything; the image is still just an image. Manage/attach use it only to surface "prompt used"
metadata in the spotlight.

### Security / cost controls

- `[[image]]` uses `api_key_env` (never in `lens.toml`). Same pattern as `[[llm]]`.
- Per-entry `max_batch` and `max_size` clamp requests server-side before dispatch, regardless of
  what the UI sends.
- No image ever becomes part of the repo until the user explicitly attaches it; discard = delete
  from the session folder.

### UI contracts

- All three modes live under `features/media/` and respect the frontend CLAUDE.md rules
  (≤300 lines per component, no network in components, no layout redefinition, address paths
  always).
- No git terminology. "Keep" and "Discard" in the carousel, not "Commit" / "Revert".
- On 401, the existing fatal-401 behavior applies unchanged.

## Open questions

1. **CF Images delivery**: do we front all mount files through Cloudflare Images, or only call it
   for thumbnail variants and let full-size pull straight from R2? Leaning toward "thumbs only"
   to keep CF Images costs predictable. Left as a config switch in phase 1.
2. **Sync vs SSE for generate**: synchronous in v1 because most image calls are <30s and it keeps
   the code simple. If latency becomes a pain, upgrade to SSE using the same
   `app.state.stream_lock` pattern as operators. Backend contract is already iterator-friendly.
3. **Old session cleanup**: no sweeper in v1. Users clean up via `/manage`. Revisit if mounts get
   large.
4. **Prompt hygiene in `/visualize`**: do we cap crafted-prompt length, or let the user edit
   freely? Starting permissive; add a soft cap if we see blow-ups in practice.
