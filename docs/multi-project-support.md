# Multi-Project Support for Lens Server

## Context

The Lens server is currently coupled to a single project: `app.state.session` holds one `ProjectSession`, and all routes are unprefixed (`/stats`, `/narrative/tree`, etc.). This means running more than one project requires more than one server instance. The goal is a single server instance that hosts multiple projects, each accessed via a `/{project_slug}/...` prefix.

Startup convention (no config): if started from a folder with `lens.toml`, one project is served. If started from a folder without `lens.toml`, direct subfolders with `lens.toml` are discovered (one level deep, once at startup). Slug = directory name.

Out of scope: changes to non-serve/dev CLI commands, deploy system.

---

## Files to Modify / Create

### Backend
1. `lens/core/project.py` — add `discover_projects(cwd)`
2. `lens/server/main.py` — change `create_app` signature, update lazy init
3. `lens/server/dependencies.py` — update `get_session`, add `get_stream_lock`
4. `lens/server/routes/projects.py` — **NEW**: `GET /projects`
5. `lens/server/routes/health.py` — add `/{project_slug}` prefix
6. `lens/server/routes/stats.py` — add `/{project_slug}` prefix
7. `lens/server/routes/narrative.py` — add `/{project_slug}` prefix
8. `lens/server/routes/narrative_mutations.py` — add `/{project_slug}` prefix
9. `lens/server/routes/operators.py` — add `/{project_slug}` prefix, update stream lock
10. `lens/server/routes/kb.py` — add `/{project_slug}` prefix
11. `lens/server/routes/transaction.py` — add `/{project_slug}` prefix
12. `lens/server/routes/attach.py` — add `/{project_slug}` prefix
13. `lens/cli/commands/serve.py` — use `discover_projects`
14. `lens/cli/commands/dev.py` — use `discover_projects` for validation

### Frontend
15. `lens/server/ui/src/stores/project.ts` — **NEW**: `currentProject`, `availableProjects`
16. `lens/server/ui/src/services/api.ts` — add `getProjects()` + `projectPath()`, update all paths
17. `lens/server/ui/src/App.svelte` — update hash parsing, add project init/switch logic
18. `lens/server/ui/src/layout/TopBar.svelte` — add project switcher `<select>`
19. `lens/server/ui/src/commands/media.ts` — fix hardcoded `/mount/file/` href
20. `lens/server/ui/src/features/cli/MediaPreviewPanel.svelte` — fix hardcoded mount paths
21. `lens/server/ui/src/preview.ts` — fix standalone preview SPA path extraction
22. `lens/server/ui/src/utils/markdown.ts` — update mount link detector to use `includes`

### Tests
23. `lens/server/test/conftest.py` — update `create_app({"test": session})`
24. `lens/server/test/test_api.py` — prefix all route paths with `/test/`
25. `lens/server/test/test_operator_stream.py` — same
26. `e2e/conftest.py` — update `create_app` call, add `project_slug` fixture
27. `e2e/tests/test_api_smoke.py` — use `project_slug` fixture in all paths
28. `e2e/tests/test_browser.py` — update hash navigation to include project slug

---

## Implementation Steps

### 1. `lens/core/project.py` — `discover_projects()`

Add after `require_lens_context`:

```python
def discover_projects(start: Path) -> list[tuple[str, Path, Path]]:
    """Returns [(slug, git_root, project_root), ...].

    If start/ is itself a project, returns [(start.name, git_root, start)].
    Otherwise scans one level deep for lens.toml in subdirectories, skipping
    dataset roots and dirs not inside a git repo.
    Raises RuntimeError if no projects found.
    """
    start = start.resolve()
    if (start / "lens.toml").exists() and not is_dataset_root(start):
        git_root = find_git_root_from(start)
        return [(start.name, git_root, start)]

    results: list[tuple[str, Path, Path]] = []
    for child in sorted(start.iterdir()):
        if not child.is_dir() or not (child / "lens.toml").exists():
            continue
        if is_dataset_root(child):
            continue
        try:
            git_root = find_git_root_from(child)
        except RuntimeError:
            continue
        results.append((child.name, git_root, child))

    if not results:
        raise RuntimeError(
            f"No Lens projects found at '{start}'. "
            "Run from a project folder or a parent containing project subfolders."
        )
    return results
```

Note: slug `"projects"` would shadow `GET /projects` — add a warning log for that case.

### 2. `lens/server/main.py` — Updated `create_app`

```python
def create_app(sessions: dict[str, ProjectSession]) -> FastAPI:
    app = FastAPI(title="Lens API")
    app.state.projects = sessions       # dict[str, ProjectSession]
    app.state.stream_locks = {}         # dict[str, StreamLock] — lazily created
    # ... route auto-discovery unchanged ...
    # ... static serving unchanged ...
    return app

def _create_app_from_cwd() -> FastAPI:
    from lens.core.project import discover_projects
    projects = discover_projects(Path.cwd())
    sessions = {slug: ProjectSession(git_root, proj)
                for slug, git_root, proj in projects}
    return create_app(sessions)
```

Remove the single `StreamLock()` creation from the old `create_app`.

### 3. `lens/server/dependencies.py` — Path-param resolution

```python
from fastapi import HTTPException, Request
from lens.core.project import ProjectSession
from lens.server.streaming import StreamLock


def get_session(project_slug: str, request: Request) -> ProjectSession:
    projects: dict[str, ProjectSession] = request.app.state.projects
    if project_slug not in projects:
        raise HTTPException(404, detail=f"Project '{project_slug}' not found")
    return projects[project_slug]


def get_stream_lock(project_slug: str, request: Request) -> StreamLock:
    locks: dict[str, StreamLock] = request.app.state.stream_locks
    if project_slug not in locks:
        locks[project_slug] = StreamLock()
    return locks[project_slug]
```

FastAPI injects `project_slug` from the `/{project_slug}` router prefix into both route handlers and their dependencies automatically.

### 4. `lens/server/routes/projects.py` — NEW (no prefix)

```python
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/projects")
def list_projects(request: Request) -> list[dict[str, str]]:
    return [{"slug": slug} for slug in request.app.state.projects]
```

### 5–12. All existing route files — Add prefix + `project_slug` param

For every file: `router = APIRouter()` → `router = APIRouter(prefix="/{project_slug}")`.

Every handler adds `project_slug: str` as a parameter (FastAPI injects it from the prefix). Handlers using only `get_session` need no other changes.

**`operators.py` — extra work:**

Refactor `_init_stream` to accept `lock` as a parameter instead of reading from `request.app.state`:

```python
def _init_stream(
    request: Request,
    session: ProjectSession,
    lock: StreamLock,
) -> tuple[Any, StreamLock, asyncio.Queue[dict[str, Any] | None], Any]:
    set_request_timezone(request.headers.get("Time-Zone"))
    narrative = _require_narrative(session)
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    on_token = _make_on_token(event_queue)
    return narrative, lock, event_queue, on_token
```

All streaming operator handlers add `lock: StreamLock = Depends(get_stream_lock)` and pass it to `_init_stream`:

```python
@router.post("/operator/write")
async def operator_write(
    body: WriteBody,
    request: Request,
    project_slug: str,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> StreamingResponse:
    narrative, lock, event_queue, on_token = _init_stream(request, session, lock)
    ...
```

`stream_cancel` uses injected lock instead of `request.app.state.stream_lock`:

```python
@router.post("/stream/cancel")
async def stream_cancel(
    project_slug: str,
    request: Request,
    session: ProjectSession = Depends(get_session),
    lock: StreamLock = Depends(get_stream_lock),
) -> dict[str, str]:
    if lock.kind is None:
        return {"status": "ok", "detail": "no stream in progress"}
    kind = lock.kind
    lock.cancel()
    ...
```

### 13–14. `serve.py` and `dev.py`

**`serve.py`:**
```python
from lens.core.project import discover_projects, ProjectSession
projects = discover_projects(Path.cwd())
sessions = {slug: ProjectSession(git_root, proj) for slug, git_root, proj in projects}
# print discovered projects, then:
uvicorn.run(create_app(sessions), host=host, port=port)
```

**`dev.py`:** Replace `require_lens_context(Path.cwd())` with `discover_projects(Path.cwd())` (wrapped in try/except for the RuntimeError → typer.Exit).

### 15. `stores/project.ts` — NEW

```typescript
import { writable } from 'svelte/store'
export const currentProject = writable<string | null>(null)
export const availableProjects = writable<string[]>([])
```

### 16. `services/api.ts` — Add prefix helper, update all paths

At the top, add:
```typescript
import { get as storeGet } from 'svelte/store'
import { currentProject } from '../stores/project'

function projectPath(path: string): string {
  const slug = storeGet(currentProject)
  if (!slug) throw new Error('No project selected')
  return `/${slug}${path}`
}

export interface ProjectInfo { slug: string }
export const getProjects = (): Promise<ProjectInfo[]> =>
  get('/projects') as Promise<ProjectInfo[]>
```

Then replace every path literal with `projectPath(...)`. The ~30 paths include:
- `getStats`, `getTree`, `getNode`, `setActiveNarrative`
- `cancelStream` (the `fetch('/stream/cancel', ...)` call)
- `runStreamingOp` callers: `runWrite`, `runPlay`, `runDesign`, `runAdvance`, `runChat`, `runEdit`, `runSectionEnd`, `runCollate`, `runCompress`
- `runWriteManual`, `runSectionStart`
- All KB calls: `getKbTags`, `getKbItems`, `getKbItem`, `saveKbItem`, `createKbItem`, `patchKbItemTags`, `deleteKbItem`, `renameKbItem`, `copyKbItem`, `getKbWithTag`
- All transaction calls: `rollbackTransaction`, `commitTransaction`, `checkpointTransaction`, `refreshTransaction`, `getTxStatus`
- All narrative mutation calls: `narrativePin`, `narrativeRewind`, `renameNode`
- All mount/attach calls: `browseMountDir`, `attachFile`, `postFormData` (inside `uploadMountFile`), `deleteMountPath`

Also export a `getMountFilePath(path: string): string` helper for use in `media.ts`:
```typescript
export function getMountFilePath(path: string): string {
  return projectPath(`/mount/file/${path}`)
}
```

### 17. `App.svelte` — Hash format and project init

**New hash format:** `project-slug/narrative/address?kb=...` (no leading `/` in the hash value, project is first segment).

Update `parseHash`:
```typescript
interface ParsedHash { project: string | null; path: string; kb: string | null }

function parseHash(hash: string): ParsedHash {
  if (!hash || hash === '#') return { project: null, path: '', kb: null }
  const raw = decodeURIComponent(hash.slice(1))
  const qIndex = raw.indexOf('?')
  const fullPath = qIndex === -1 ? raw : raw.slice(0, qIndex)
  const kb = qIndex === -1 ? null : new URLSearchParams(raw.slice(qIndex + 1)).get('kb')
  const stripped = fullPath.startsWith('/') ? fullPath.slice(1) : fullPath
  const slashIdx = stripped.indexOf('/')
  if (slashIdx === -1) return { project: stripped || null, path: '', kb }
  return { project: stripped.slice(0, slashIdx), path: stripped.slice(slashIdx + 1), kb }
}
```

Update `buildHash` to include project from store:
```typescript
function buildHash(path: string, kb: string | null): string {
  const slug = get(currentProject) ?? ''
  const base = path ? `${slug}/${path}` : slug
  return kb ? `${base}?kb=${encodeURIComponent(kb)}` : base
}
```

Updated `onMount` init:
```typescript
import { currentProject, availableProjects } from './stores/project'
import { getProjects } from './services/api'

onMount(async () => {
  window.addEventListener('hashchange', handleHashChange)
  onAfterMutation(() => { void getStats().then(applyStats) })

  try {
    // 1. Load project list
    const projectList = await getProjects()
    const slugs = projectList.map(p => p.slug)
    availableProjects.set(slugs)

    // 2. Pick project from hash or default to first
    const { project: hashProject, path, kb } = parseHash(window.location.hash)
    const selectedSlug = (hashProject && slugs.includes(hashProject))
      ? hashProject : (slugs[0] ?? null)
    if (!selectedSlug) { console.error('No projects available'); return }
    currentProject.set(selectedSlug)

    // 3. Fetch stats (now uses projectPath() via currentProject store)
    const initialStats = await getStats()
    applyStats(initialStats)

    // 4. Navigate
    if (path) {
      try {
        inlineEditMode.set(null)
        const data = await getNode(path)
        currentAddress.set(data.address)
        nodeContent.set(data.content)
        window.location.hash = buildHash(data.address, hashKbParam())
      } catch {
        window.location.hash = buildHash('', kb)
        await navigate(initialStats.cursor || '')
      }
    } else {
      await navigate(initialStats.cursor || '')
    }
    applyKbFromUrl(kb)
  } catch (e) { console.error('Init failed:', e) }
})
```

Add `switchProject` function (passed as prop to TopBar):
```typescript
async function switchProject(slug: string): Promise<void> {
  currentProject.set(slug)
  currentAddress.set(null)
  nodeContent.set('')
  const newStats = await getStats()
  applyStats(newStats)
  await navigate(newStats.cursor || '')
}
```

Update `handleHashChange` to handle project changes in the hash:
```typescript
async function handleHashChange() {
  const { project, path, kb } = parseHash(window.location.hash)
  const currentSlug = get(currentProject)
  if (project && project !== currentSlug) {
    await switchProject(project)
    applyKbFromUrl(kb)
    return
  }
  const addr = get(currentAddress)
  if (path && path !== addr) navigate(path)
  applyKbFromUrl(kb)
}
```

Update `_updateUrlKb` — `buildHash` now reads project from store automatically, no change needed.

Update TopBar usage: `<TopBar onProjectSwitch={switchProject} />`.

Also update the parent link in TopBar: `href="#{parentAddr}"` needs project prefix. Fix by computing in TopBar using `currentProject` store:

```svelte
$: parentHash = parentAddr ? `${$currentProject ?? ''}/${parentAddr}` : null
<!-- then: href="#{parentHash}" -->
```

### 18. `TopBar.svelte` — Project switcher

```svelte
<script lang="ts">
  import { currentProject, availableProjects } from '../stores/project'
  export let onProjectSwitch: ((slug: string) => Promise<void>) | undefined = undefined

  function handleProjectChange(e: Event) {
    const slug = (e.target as HTMLSelectElement).value
    if (slug && slug !== $currentProject) onProjectSwitch?.(slug)
  }
</script>

<!-- In normal mode, after hamburger button: -->
{#if $availableProjects.length > 1}
  <select class="project-select" value={$currentProject ?? ''} on:change={handleProjectChange}
          aria-label="Select project">
    {#each $availableProjects as slug}
      <option value={slug}>{slug}</option>
    {/each}
  </select>
{/if}
```

When only one project, no dropdown (keeps UI clean for common case).

### 19. `media.ts` — Fix download href

Replace `a.href = \`/mount/file/${path}\`` with:
```typescript
import { getMountFilePath } from '../services/api'
a.href = getMountFilePath(path)
```

### 20. `MediaPreviewPanel.svelte` — Fix embedded paths

Add reactive prefix for `src` attributes:
```typescript
import { currentProject } from '../../stores/project'
$: prefix = $currentProject ? `/${$currentProject}` : ''
```
Then prefix the `/mount/preview/...` and `/mount/file/...` URLs with `{prefix}`.

### 21. `preview.ts` — Standalone preview SPA

Extract slug from the page's own pathname (this file runs in a non-Svelte context):
```typescript
const slugMatch = window.location.pathname.match(/^\/([^/]+)\/mount\//)
const slug = slugMatch ? slugMatch[1] : ''
const pathMatch = window.location.pathname.match(/\/mount\/preview\/(.+)$/)
const filePath = pathMatch ? pathMatch[1] : ''
fetch(`/${slug}/mount/file/${filePath}`)
```

### 22. `markdown.ts` — Mount link detection

Change `href?.startsWith('/mount/file/')` to `href?.includes('/mount/file/')` (and same for `/mount/preview/`) so it handles both legacy and project-prefixed URLs.

### 23–28. Tests

Use `"test"` as the hardcoded slug in all server unit/integration test fixtures:
```python
app = create_app({"test": session})
```
All test route paths gain `/test/` prefix (search-and-replace).

For e2e, add a `project_slug` fixture to `e2e/conftest.py`:
```python
@pytest.fixture(scope="session")
def project_slug(lens_project_dir: Path | None) -> str:
    return lens_project_dir.name if lens_project_dir else \
        json.loads(urllib.request.urlopen(f"{os.environ['LENS_DEV_SERVER_URL']}/projects").read())[0]["slug"]
```
Update `e2e/conftest.py`'s `create_app` call: `create_app({lens_project_dir.name: session})`.
All e2e test paths use `f"/{project_slug}/..."`.

---

## Edge Cases / Tricky Parts

- **`/{project_slug}` prefix + `/{address:path}`**: FastAPI handles greedy `:path` captures correctly when prefixed.
- **`stream_locks` dict**: Safe without a mutex — asyncio is single-threaded; dict access can't interleave.
- **`_LazyApp` reload**: Class variable resets on module reload; `_create_app_from_cwd()` re-runs `discover_projects` — correct behavior.
- **KnowledgeStore caching**: Already per-project via `_registry: dict[Path, KnowledgeStore]`. No changes needed.
- **Slug `"projects"` conflict**: Log a warning if discovered; it would shadow `GET /projects`.
- **Hash backward compatibility**: Old `#/chapter-1` bookmarks break — acceptable per requirements.

---

## Verification

1. `poe check` must pass (lint, typecheck, unit, integration, e2e).
2. Start from project folder → one project; `GET /projects` returns `[{"slug": "<dirname>"}]`.
3. Start from parent folder → multiple projects; all accessible by slug.
4. UI hash includes project slug: `#my-project/chapter-1`.
5. Project dropdown visible only when >1 project available.
6. Switching projects reloads stats and navigates to cursor of new project.
7. Per-project stream locks: streaming in one project does not block another.
