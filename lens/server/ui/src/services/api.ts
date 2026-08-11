import { get as storeGet } from 'svelte/store'
import { currentProject } from '../stores/project'
import { releaseInfo } from '../stores/release'

function projectPath(path: string): string {
  const slug = storeGet(currentProject)
  if (!slug) throw new Error('No project selected')
  return `/${slug}${path}`
}

function _updateReleaseFromResponse(data: unknown): void {
  if (data && typeof data === 'object' && 'release' in data) {
    const rls = (data as { release: unknown }).release
    if (rls && typeof rls === 'object') {
      releaseInfo.update((prev) => ({
        ...(prev ?? {
          enabled: false,
          lens_repo_url: '',
          requested_version: '',
          requested_from_commit: '',
          app_leader: false,
          dataset_repos: [],
          installed_version: null,
          latest_available: null,
          update_available: false,
        } as ReleaseInfo),
        ...(rls as Partial<ReleaseInfo>),
      }))
    }
  }
}

export function getMountFilePath(path: string): string {
  return projectPath(`/mount/file/${path}`)
}

export async function fetchMountFileText(path: string): Promise<string> {
  const url = getMountFilePath(path)
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${url}`)
  return r.text()
}

async function get(path: string): Promise<unknown> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`)
  const data = await r.json()
  _updateReleaseFromResponse(data)
  return data
}

async function post(path: string, body: unknown): Promise<unknown> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`)
  const data = await r.json()
  _updateReleaseFromResponse(data)
  return data
}

async function put(path: string, body: unknown): Promise<unknown> {
  const r = await fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`)
  return r.json()
}

async function patch(path: string, body: unknown): Promise<unknown> {
  const r = await fetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorDetail(r))
  return r.json()
}

async function del(path: string): Promise<unknown> {
  const r = await fetch(path, { method: 'DELETE' })
  if (!r.ok) throw new Error(await errorDetail(r))
  const text = await r.text()
  return text ? JSON.parse(text) : undefined
}

export interface ProjectInfo {
  slug: string
}

export const getProjects = (): Promise<ProjectInfo[]> =>
  get('/projects') as Promise<ProjectInfo[]>

/** One configured ``[[image]]`` row from the project (API `/stats`). */
export interface ImageBackendStats {
  id: string
  api: string
  model: string
  aspect_ratios: string[]
  sizes: string[]
  default_aspect: string
  default_size: string
  default_batch: number
  max_batch: number
  max_prompt_chars: number
  /** Mount-relative reference images as API input when the backend declares support. */
  supports_reference_images: boolean
}

export interface Stats {
  active_narrative: string | null
  narratives: string[]
  cursor: string | null
  has_pending: boolean
  has_staged: boolean
  pending_owner: string | null
  dataset_name: string | null
  current_datasets: string[] | null
  kb_types: string[]
  kb_count: number
  effective_pins_at_cursor: string[] | null
  /** Inherited ``vars`` at the narrative cursor (root → leaf). */
  effective_vars_at_cursor: Record<string, string>
  /** Merged pinned params at cursor; keys ``global:<name>`` or ``<op_slug>:<name>``, string values. */
  effective_params_at_cursor: Record<string, string>
  /** KB ids in the effective pin crawl that carry `remember.*` tags → those tags. */
  remember_pins_at_cursor: Record<string, string[]>
  /** Pinned ids tagged `state` — rendered at the prompt tail, re-sent every beat. */
  state_pins_at_cursor: string[] | null
  /** Includes written into the cursor node — in scope for the rest of the node. */
  include_ids_at_cursor: string[] | null
  /** Mentions still expanding at the cursor — good for one more AI turn. */
  mention_ids_at_cursor: string[] | null
  available_llms: string[]
  image_backends: ImageBackendStats[]
  has_mount: boolean
  /** True when mount_point is s3:// (presigned URLs / reference images for APIs). */
  cloud_mount: boolean
  /** True when at least one configured ``[[image]]`` API accepts reference images. */
  reference_images_supported: boolean
  /** True when ``mount_point`` and a usable ``[[speech]]`` backend (incl. API key) are configured. */
  tts_available: boolean
  active_session_operator: string | null
  transaction: TransactionState | null
  dataset_configs: Record<string, Record<string, unknown>>
  /** Release system status (null when viewing a dataset or release not enabled). */
  release: ReleaseStats | null
  /**
   * One entry per modality that's either configured in front matter at the
   * cursor (root → leaf merge) or was a resolution candidate. `config` is
   * the raw merged front-matter object; `active`/`reason` are the fully
   * gated resolved state. A modality with no front-matter entry anywhere in
   * the ancestor chain is simply absent from this dict.
   */
  modalities_at_cursor: Record<string, ModalityAtCursor>
}

export interface ModalityAtCursor {
  config: Record<string, unknown>
  active: boolean
  reason?: string
}

export interface ReleaseStats {
  enabled: boolean
  lens_repo_url: string
  requested_version: string
  requested_from_commit: string
  app_leader: boolean
  dataset_repos: { name: string; git_url: string; ref: string }[]
  installed_version: string | null
}

export interface ReleaseInfo {
  enabled: boolean
  lens_repo_url: string
  requested_version: string
  requested_from_commit: string
  app_leader: boolean
  dataset_repos: { name: string; git_url: string; ref: string }[]
  installed_version: string | null
  latest_available: string | null
  update_available: boolean
}

export interface TransactionState {
  has_pending: boolean
  owner: string | null
  is_mutation: boolean
  raw_diff: string
}

export interface TreeNode {
  address: string
  key: string
  children: TreeNode[]
  hasHiddenChildren?: boolean
}

export interface NodeData {
  address: string
  content: string
  children: string[]
}

export const getStats = (): Promise<Stats> =>
  get(projectPath('/stats')) as Promise<Stats>
export const getTree = (): Promise<TreeNode[]> =>
  get(projectPath('/narrative/tree')) as Promise<TreeNode[]>
export const getNode = (addr: string): Promise<NodeData> =>
  get(projectPath(`/narrative/node/${addr}`)) as Promise<NodeData>

// ---- Prompt composition report (`GET /{slug}/explain`) ----

/** Prefix = stable across calls (cacheable); volatile = changes every call. */
export type ExplainCache = 'prefix' | 'volatile'

/** One measured unit of the assembled prompt. */
export interface ExplainComponent {
  id: string
  kind: string
  block: string
  order: number
  bytes: number
  tokens: number
  /** Share of the grand total, already rounded server-side. */
  percent: number
  /** The sentence a human reads: why this is in the prompt. */
  provenance: string
  /** Machine-readable provenance: `node_pin`, `expansion`, `mention`, … */
  provenance_kind: string
  cache: ExplainCache
  /** Structured provenance bits: `pin_node`, `kb_id`, `tags`, … */
  detail: Record<string, string>
}

/** A rendered prompt block plus the components inside it. */
export interface ExplainBlock {
  id: string
  label: string
  role: string
  order: number
  bytes: number
  tokens: number
  percent: number
  /** Block header/footer and separators — part of the block, not a child row. */
  framing_bytes: number
  framing_tokens: number
  cache: ExplainCache
  components: ExplainComponent[]
}

export interface ExplainTotals {
  bytes: number
  tokens: number
  accounted_bytes: number
  /** Message separators — the residual outside any block. */
  other_bytes: number
  other_tokens: number
  messages: number
  message_bytes: number[]
}

export interface ExplainReport {
  address: string
  node: string
  operator: string
  line: number | null
  blocks: ExplainBlock[]
  /** Components that resolved but are not sent (e.g. unresolved `@` tokens). */
  excluded: ExplainComponent[]
  totals: ExplainTotals
  chars_per_token: number
  active_modalities: string[]
  pinned_ids: string[]
  /** Includes/mentions expanded inside the passage; their bytes are already in a block. */
  in_place: ExplainInPlace[]
  warnings: string[]
}

export interface ExplainInPlace {
  kind: 'include' | 'mention'
  kb_id: string
  bytes: number
  tokens: number
}

export interface ExplainParams {
  address?: string
  line?: number
  operator?: string
}

/** Read-only: no transaction, no model call — safe to refetch on cursor move. */
export async function getExplain(params: ExplainParams = {}): Promise<ExplainReport> {
  const query = new URLSearchParams()
  if (params.address) query.set('address', params.address)
  if (params.line !== undefined) query.set('line', String(params.line))
  if (params.operator) query.set('operator', params.operator)
  const suffix = query.toString()
  const path = projectPath(`/explain${suffix ? `?${suffix}` : ''}`)
  const r = await fetch(path)
  if (!r.ok) throw new Error(await errorDetail(r))
  return (await r.json()) as ExplainReport
}

export type NarrativeKind = 'default' | 'companion_chat'

export interface SetActiveNarrativeOptions {
  narrativeKind?: NarrativeKind
  companionAsKbId?: string
  companionWithKbId?: string
}

export const setActiveNarrative = withStats(
  (
    slug: string,
    options?: SetActiveNarrativeOptions
  ): Promise<{ active: string; companion_bootstrap?: string }> =>
    post(projectPath('/narrative/narratives/active'), {
      narrative: slug,
      ...(options?.narrativeKind === 'companion_chat'
        ? {
            narrative_kind: 'companion_chat',
            companion_as_kb_id: options.companionAsKbId ?? '',
            companion_with_kb_id: options.companionWithKbId ?? '',
          }
        : { narrative_kind: 'default' as const }),
    }) as Promise<{ active: string; companion_bootstrap?: string }>
)

// ---- Post-mutation stats refresh ----
// App registers a callback here; withStats() fires it after every mutation.
// This avoids a circular import between api.ts and stores/stats.ts.

let _afterMutation: (() => void) | null = null

export function onAfterMutation(fn: () => void): void {
  _afterMutation = fn
}

function withStats<A extends unknown[], R>(
  fn: (...args: A) => Promise<R>
): (...args: A) => Promise<R> {
  return async (...args: A): Promise<R> => {
    const result = await fn(...args)
    _afterMutation?.()
    return result
  }
}

async function errorDetail(r: Response): Promise<string> {
  try {
    const data = (await r.json()) as { detail?: string }
    if (typeof data.detail === 'string') return data.detail
  } catch {
    /* ignore */
  }
  return `HTTP ${r.status}: ${r.url}`
}

// ---- Unified stream cancel ----

export async function cancelStream(): Promise<void> {
  const r = await fetch(projectPath('/stream/cancel'), { method: 'POST' })
  if (!r.ok) throw new Error(`HTTP ${r.status}: /stream/cancel`)
}

export async function workflowStreamAction(
  stepId: string,
  action: 'retry' | 'skip'
): Promise<void> {
  const r = await fetch(projectPath('/stream/workflow/action'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ step_id: stepId, action }),
  })
  if (!r.ok) throw new Error(await errorDetail(r))
}

// ---- Media generate (SSE) + incremental save ----

export interface MediaGenerateParams {
  prompt?: string
  model?: string
  aspect?: string
  size?: string
  batch?: number
  slug?: string
  negative?: string
  from?: string
  /** Mount-relative paths; S3 mount only. */
  refs?: string[]
}

export interface MediaStartEvent {
  type: 'start'
  slug: string
  model_id: string
  api: string
  model: string
  aspect: string
  size: string
  batch_size: number
  prompt_raw: string
  prompt_resolved: string
  negative?: string | null
  /** Mount-relative ref paths (same as generate request); omitted if none. */
  refs?: string[]
}

export interface MediaItemEvent {
  type: 'item'
  index: number
  ext: string
  b64: string
  metadata?: Record<string, unknown>
}

export interface MediaProgressEvent {
  type: 'progress'
  phase: string
  pct?: number | null
  message?: string | null
}

export interface MediaDoneEvent {
  type: 'done'
}

export interface MediaErrorEvent {
  type: 'error'
  message: string
}

export type MediaGenerateEvent =
  | MediaStartEvent
  | MediaItemEvent
  | MediaProgressEvent
  | MediaDoneEvent
  | MediaErrorEvent

export async function runMediaGenerate(
  params: MediaGenerateParams,
  onEvent: (event: MediaGenerateEvent) => void
): Promise<MediaDoneEvent | MediaErrorEvent> {
  const r = await fetch(projectPath('/generate'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: params.prompt,
      model: params.model,
      aspect: params.aspect,
      size: params.size,
      batch: params.batch,
      slug: params.slug,
      negative: params.negative,
      from: params.from,
      ...(params.refs?.length ? { refs: params.refs } : {}),
    }),
  })
  if (r.status === 409 || r.status === 423) {
    throw new StreamBusyError(await errorDetail(r), r.status)
  }
  if (!r.ok) throw new Error(await errorDetail(r))
  const responseBody = r.body
  if (responseBody === null) throw new Error('No response body')
  const { parseSSEFromStream } = await import('./sse')
  let lastEvent: MediaDoneEvent | MediaErrorEvent = {
    type: 'error',
    message: 'Stream ended without done event',
  }
  for await (const event of parseSSEFromStream(responseBody)) {
    const parsed = JSON.parse(event.data) as MediaGenerateEvent
    onEvent(parsed)
    if (parsed.type === 'done' || parsed.type === 'error') {
      lastEvent = parsed
    }
  }
  return lastEvent
}

export interface SaveGeneratedItemBody {
  slug: string
  batch_seq?: number | null
  batch_params: {
    prompt_raw: string
    prompt_resolved: string
    model_id: string
    aspect_ratio: string
    size: string
    batch_size: number
    negative?: string | null
    refs?: string[] | null
  }
  item: { index: number; ext: string; b64: string }
}

export interface SaveGeneratedItemResult {
  batch_seq: number
  result_seq: number
  path: string
  sidecar_path: string
  sidecar_created: boolean
}

export const saveGeneratedItem = (body: SaveGeneratedItemBody): Promise<SaveGeneratedItemResult> =>
  post(projectPath('/generate/save'), body) as Promise<SaveGeneratedItemResult>

// ---- Media composite (chromakey) preview + save ----

export interface ChromakeyParams {
  path: string
  key?: string
  coreTol?: number
  residualThresh?: number
  dilatePx?: number
}

export interface ChromakeyPreviewResult {
  /** Null when `preview_skipped` — an animated source is not rendered. */
  png_b64: string | null
  key_hex: string | null
  core_tol: number | null
  residual_thresh: number | null
  dilate_px: number | null
  n_corners_used: number | null
  n_frames: number
  /** Animated source: keying every frame to preview would double the save's work. */
  preview_skipped: boolean
}

export interface ChromakeySaveResult {
  output_path: string
  key_hex: string
  core_tol: number
  residual_thresh: number
  dilate_px: number
  n_corners_used: number
  n_frames: number
  palette_colors: number | null
}

function chromakeyRequestBody(params: ChromakeyParams): Record<string, unknown> {
  return {
    path: params.path,
    key: params.key,
    core_tol: params.coreTol,
    residual_thresh: params.residualThresh,
    dilate_px: params.dilatePx,
  }
}

export async function previewChromakey(params: ChromakeyParams): Promise<ChromakeyPreviewResult> {
  const r = await fetch(projectPath('/mount/composite/chromakey/preview'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(chromakeyRequestBody(params)),
  })
  if (!r.ok) throw new Error(await errorDetail(r))
  return r.json() as Promise<ChromakeyPreviewResult>
}

export async function saveChromakey(
  params: ChromakeyParams & { outPath?: string }
): Promise<ChromakeySaveResult> {
  const r = await fetch(projectPath('/mount/composite/chromakey/save'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...chromakeyRequestBody(params), out_path: params.outPath }),
  })
  if (!r.ok) throw new Error(await errorDetail(r))
  return r.json() as Promise<ChromakeySaveResult>
}

// ---- Operator streaming API ----

export interface OperatorTargetEvent {
  type: 'target'
  node: string
}

export interface OperatorTokenEvent {
  type: 'token'
  text: string
  step_id?: string
}

export interface OperatorDoneEvent {
  type: 'done'
  operator: string
  node: string
  interrupted: boolean
  inserted?: string[]
  updated?: string[]
  errors?: string[]
  section_key?: string
  workflow_outcome?: 'success' | 'partial' | 'failed' | 'cancelled'
  steps?: WorkflowStepSnapshot[]
}

export interface OperatorErrorEvent {
  type: 'error'
  message: string
}

/** LLM / operator lifecycle (before first streamed token). */
export interface OperatorProgressEvent {
  type: 'progress'
  phase: string
  message?: string
  operator?: string
  model?: string
  host?: string
  llm_id?: string
  message_count?: number
  round?: number
  iteration?: number
  http_status?: number
  elapsed_ms?: number
  interrupted?: boolean
  step_id?: string
}

/** Post-operator notice (e.g. auto-compress ran but model did not collate). */
export interface OperatorInfoEvent {
  type: 'info'
  code?: string
  message?: string
}

/** Structured tool-call event (design operator with STRUCTURED policy). */
export interface OperatorToolEvent {
  type: 'tool_call'
  name?: string
  summary?: string
}

export type WorkflowStepStatus =
  | 'planned'
  | 'running'
  | 'success'
  | 'skipped'
  | 'failed'
  | 'cancelled'

export interface WorkflowStepSnapshot {
  id: string
  label: string
  status: WorkflowStepStatus
  error?: string
  /** Non-fatal issues (step still ``success``); UI shows muted text. */
  warnings?: string[]
  skippable?: boolean
  /** Cancel mid-step rolls back the whole operator preview (e.g. collate). */
  abort_rolls_back?: boolean
}

export interface OperatorWorkflowEvent {
  type: 'workflow'
  action: 'plan' | 'step_start' | 'step_end' | 'step_failed'
  steps?: WorkflowStepSnapshot[]
  step_id?: string
  label?: string
  status?: WorkflowStepStatus
  error?: string
  retryable?: boolean
  warnings?: string[]
}

export type OperatorEvent =
  | OperatorTargetEvent
  | OperatorTokenEvent
  | OperatorDoneEvent
  | OperatorErrorEvent
  | OperatorProgressEvent
  | OperatorInfoEvent
  | OperatorToolEvent
  | OperatorWorkflowEvent

export class StreamBusyError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message)
    this.name = 'StreamBusyError'
  }
}

async function runStreamingOp(
  url: string,
  body: unknown,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Time-Zone': tz },
    body: JSON.stringify(body),
  })
  if (r.status === 409 || r.status === 423) {
    throw new StreamBusyError(await errorDetail(r), r.status)
  }
  if (!r.ok) throw new Error(await errorDetail(r))
  const responseBody = r.body
  if (responseBody === null) throw new Error('No response body')
  const { parseSSEFromStream } = await import('./sse')
  let lastEvent: OperatorDoneEvent | OperatorErrorEvent = {
    type: 'error',
    message: 'Stream ended without done event',
  }
  for await (const event of parseSSEFromStream(responseBody)) {
    const parsed = JSON.parse(event.data) as OperatorEvent
    onEvent(parsed)
    if (parsed.type === 'done' || parsed.type === 'error') {
      lastEvent = parsed
    }
  }
  return lastEvent
}

export interface WriteParams {
  prompt?: string
  pins?: string[]
  unpins?: string[]
  mentions?: string[]
  includes?: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
}

export const runWrite = (
  params: WriteParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/write'), params, onEvent)

export interface WriteManualResult {
  status: string
  node: string
}

export const runWriteManual = withStats((
  params: { text: string }
): Promise<WriteManualResult> =>
  post(projectPath('/operator/write/manual'), params) as Promise<WriteManualResult>
)

export interface PlayParams {
  prompt?: string
  module_id?: string
  pins?: string[]
  unpins?: string[]
  mentions?: string[]
  includes?: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
  end?: boolean
  as_pc?: string
  do_pass?: boolean
  slug?: string
}

export const runPlay = (
  params: PlayParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/play'), params, onEvent)

export interface DesignParams {
  prompt?: string
  module_id?: string
  pins?: string[]
  unpins?: string[]
  mentions?: string[]
  includes?: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
  end?: boolean
  slug?: string
}

export const runDesign = (
  params: DesignParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/design'), params, onEvent)

export interface AdvanceParams {
  days?: number
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
  feedback?: string
  end?: boolean
}

export const runAdvance = (
  params: AdvanceParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/advance'), params, onEvent)

export interface ChatParams {
  prompt?: string
  as_kb_id?: string
  with_kb_id?: string
  narrate?: boolean
  wait?: boolean
  pins?: string[]
  unpins?: string[]
  mentions?: string[]
  includes?: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
  end?: boolean
  slug?: string
}

export const runChat = (
  params: ChatParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/chat'), params, onEvent)

export interface EditParams {
  address: string
  start_line: number
  end_line: number
  prompt?: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
  replace?: boolean
  replacement?: string
}

export const runEdit = (
  params: EditParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/edit'), params, onEvent)

export interface KbEditParams {
  id: string
  instruction: string
  context?: string
  include_template?: boolean
  pins: string[]
  unpins: string[]
  llm_id?: string
  reasoning?: string
  retry?: boolean
}

export const runKbEdit = (
  params: KbEditParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/kb/edit'), params, onEvent)

export interface SectionStartParams {
  id: string
  pins?: string[]
  unpins?: string[]
}

export interface SectionStartResult {
  status: string
  node: string
}

export const runSectionStart = withStats((
  params: SectionStartParams
): Promise<SectionStartResult> =>
  post(projectPath('/operator/section/start'), params) as Promise<SectionStartResult>
)

export interface SectionEndParams {
  llm_id?: string
  reasoning?: string
  summary_guide?: string
}

export const runSectionEnd = (
  params: SectionEndParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/section/end'), params, onEvent)

export interface CollateParams {
  id: string
  address: string
  start_line: number
  end_line: number
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  reasoning?: string
  summary_guide?: string
}

export const runCollate = (
  params: CollateParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/collate'), params, onEvent)

export type CompressAggressiveness = 'low' | 'medium' | 'high'

export interface CompressParams {
  /** What to collate; omit when using `aggressiveness`. */
  prompt?: string
  aggressiveness?: CompressAggressiveness
  /** Narrative node (nav or display form); omit for cursor node. */
  address?: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  reasoning?: string
  summary_guide?: string
}

export const runCompress = (
  params: CompressParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp(projectPath('/operator/compress'), params, onEvent)

// ---- KB API ----

export interface KbItem {
  id: string
  tags: string[]
}

export interface KbItemDetail {
  id: string
  type: string
  content: string
  tags: string[]
}

export const getKbTags = (params?: { type?: string; prefix?: string }): Promise<string[]> => {
  const qs = new URLSearchParams()
  if (params?.type) qs.set('type', params.type)
  if (params?.prefix) qs.set('prefix', params.prefix)
  const query = qs.toString()
  return get(projectPath(`/kb/tags${query ? '?' + query : ''}`)) as Promise<string[]>
}

export const getKbItems = (params?: { type?: string; tags?: string }): Promise<KbItem[]> => {
  const qs = new URLSearchParams()
  if (params?.type) qs.set('type', params.type)
  if (params?.tags) qs.set('tags', params.tags)
  const query = qs.toString()
  return get(projectPath(`/kb/items${query ? '?' + query : ''}`)) as Promise<KbItem[]>
}

export const getKbItem = (id: string): Promise<KbItemDetail> =>
  get(projectPath(`/kb/item/${id}`)) as Promise<KbItemDetail>

export const saveKbItem = withStats((id: string, content: string): Promise<{ id: string }> =>
  put(projectPath(`/kb/item/${id}`), { content }) as Promise<{ id: string }>
)

/** Like `saveKbItem` but skips the post-mutation stats refresh.
 *  Used for inline editable controls (checkboxes, counters, notes) where
 *  stats-triggered re-render would destroy the focused input element. */
export async function saveKbItemSilent(id: string, content: string): Promise<{ id: string }> {
  return put(projectPath(`/kb/item/${id}`), { content }) as Promise<{ id: string }>
}

export const createKbItem = withStats((
  id: string,
  content?: string,
  useTemplate?: boolean
): Promise<{ id: string; content: string }> =>
  post(projectPath('/kb/items'), { id, content, use_template: useTemplate ?? false }) as Promise<{
    id: string
    content: string
  }>
)

export interface KbTagResponse {
  id: string
  tags: string[]
  invalid_dot_tags?: string[]
}

export interface KbCopyResponse {
  source_id: string
  target_id: string
}

export interface KbRenameResponse {
  old_id: string
  new_id: string
}

export const patchKbItemTags = withStats((
  id: string,
  body: { add: string[]; remove: string[] }
): Promise<KbTagResponse> =>
  patch(projectPath(`/kb/item/${encodeURIComponent(id)}/tags`), body) as Promise<KbTagResponse>
)

export const deleteKbItem = withStats((id: string): Promise<{ id: string }> =>
  del(projectPath(`/kb/item/${encodeURIComponent(id)}`)) as Promise<{ id: string }>
)

export const renameKbItem = withStats((oldId: string, newId: string): Promise<KbRenameResponse> =>
  post(projectPath('/kb/rename'), { old_id: oldId, new_id: newId }) as Promise<KbRenameResponse>
)

export const copyKbItem = withStats((sourceId: string, targetId: string): Promise<KbCopyResponse> =>
  post(projectPath('/kb/copy'), { source_id: sourceId, target_id: targetId }) as Promise<KbCopyResponse>
)

export interface KbWithTagResponse {
  ids: string[]
  layers?: { parent: string; children: string[] }[]
  objects?: Record<string, KbItemDetail>
  id_to_tags?: Record<string, string[]>
}

export const getKbWithTag = (
  tags: string[],
  options?: { expand?: boolean; recurse?: number | null; same_type_only?: boolean; type_filter?: string | null }
): Promise<KbWithTagResponse> =>
  post(projectPath('/kb/with-tag'), { tags, ...options }) as Promise<KbWithTagResponse>

// ---- Transaction API ----

export interface TransactionActionResponse {
  status: 'ok' | 'error'
  detail?: string
  owner?: string | null
  is_mutation?: boolean
  release?: ReleaseInfo | null
}

export const rollbackTransaction = (): Promise<TransactionActionResponse> =>
  post(projectPath('/rollback'), {}) as Promise<TransactionActionResponse>

export const commitTransaction = (): Promise<TransactionActionResponse> =>
  post(projectPath('/commit'), {}) as Promise<TransactionActionResponse>

export const checkpointTransaction = (opts?: {
  message?: string
  push?: boolean
}): Promise<TransactionActionResponse> =>
  post(projectPath('/checkpoint'), opts ?? {}) as Promise<TransactionActionResponse>

export interface RefreshEntry {
  name: string
  status: string
  action: string
  detail: string
}

export interface RefreshResponse {
  status: 'ok' | 'error'
  entries?: RefreshEntry[]
  any_changed?: boolean
  detail?: string
  release?: ReleaseInfo | null
}

export const refreshTransaction = (opts?: {
  reset?: boolean
}): Promise<RefreshResponse> =>
  post(projectPath('/refresh'), opts ?? {}) as Promise<RefreshResponse>

export interface TxStatusCommit {
  hash: string
  message: string
}

export interface TxStatusResponse {
  pending_files: string[]
  staged_files: string[]
  has_remote: boolean
  has_upstream: boolean
  fetch_error: string | null
  incoming: TxStatusCommit[]
  unpushed: TxStatusCommit[]
  remote_head: TxStatusCommit | null
  release?: ReleaseInfo | null
}

export const getTxStatus = (): Promise<TxStatusResponse> =>
  get(projectPath('/tx/status')) as Promise<TxStatusResponse>

// ---- Release API ----

export interface ReleaseLatestResponse {
  latest_available: string | null
  update_available: boolean
}

export const fetchLatestRelease = (): Promise<ReleaseLatestResponse> =>
  get(projectPath('/release/latest')) as Promise<ReleaseLatestResponse>

export const releaseRequest = (targetVersion: string): Promise<{
  status: 'ok' | 'error'
  requested_version?: string
  requested_from_commit?: string
  detail?: string
}> =>
  post(projectPath('/release/request'), {
    target_version: targetVersion,
  }) as Promise<{
    status: 'ok' | 'error'
    requested_version?: string
    requested_from_commit?: string
    detail?: string
  }>

export const releaseClear = (): Promise<{
  status: 'ok' | 'error'
  detail?: string
}> =>
  post(projectPath('/release/clear'), {}) as Promise<{
    status: 'ok' | 'error'
    detail?: string
  }>

// ---- Narrative API ----

export type NarrativePinBody =
  | {
      kind?: 'kb'
      operation: 'add' | 'remove' | 'block' | 'unblock' | 'mention' | 'include'
      ids: string[]
      node?: string | null
    }
  | {
      kind: 'var'
      operation: 'set' | 'unset'
      key: string
      value?: string | number | boolean | null
      node?: string | null
    }
  | {
      kind: 'param'
      operation: 'set' | 'unset'
      scope: string
      key: string
      value?: string | number | boolean | null
      node?: string | null
    }
  | {
      kind: 'modality'
      operation: 'set' | 'unset'
      modality_id: string
      key: string
      value?: string | number | boolean | null
      node?: string | null
    }

export interface PinResponse {
  status: 'ok' | 'error'
  count?: number
  target?: string
  detail?: string
}

export const narrativePin = withStats(
  (body: NarrativePinBody): Promise<PinResponse> =>
    post(projectPath('/narrative/pin'), body) as Promise<PinResponse>
)

export interface RewindParams {
  address: string
  line?: number | null
}

export interface RewindResponse {
  status: 'ok' | 'error'
  address?: string
  line?: number | null
  detail?: string
}

export const narrativeRewind = withStats((params: RewindParams): Promise<RewindResponse> =>
  post(projectPath('/narrative/rewind'), params) as Promise<RewindResponse>
)

export interface RenameNodeParams {
  address: string
  new_slug: string
}

export interface RenameNodeResponse {
  status: 'ok' | 'error'
  address?: string
  new_slug?: string
  detail?: string
}

export const renameNode = withStats((params: RenameNodeParams): Promise<RenameNodeResponse> =>
  post(projectPath('/narrative/rename'), params) as Promise<RenameNodeResponse>
)

export interface MountEntry {
  name: string
  is_dir: boolean
  /** Preview stream: skeleton tile until the image arrives */
  placeholder?: boolean
}

export interface AttachResponse {
  status: string
  type?: string
  embed?: string
  detail?: string
}

export interface AttachParams {
  address?: string
  line?: number
  /** Foreground layer path; when set, `path` is the background of a composite attachment. */
  fgPath?: string
}

export const browseMountDir = (path = ''): Promise<MountEntry[]> =>
  get(projectPath(`/mount/browse?path=${encodeURIComponent(path)}`)) as Promise<MountEntry[]>

/** One search hit: flattened metadata (reserved path-derived keys + sidecar keys) plus its relevance score. */
export interface SearchMediaItem {
  relative_path: string
  name: string
  extension: string
  type: string
  _score: number
  [key: string]: unknown
}

export interface SearchMediaPage {
  items: SearchMediaItem[]
  total_items: number
  total_pages: number
  page_size: number
  current_page: number
}

export const searchMedia = (query: string, page = 1): Promise<SearchMediaPage> =>
  get(
    projectPath(`/mount/search?q=${encodeURIComponent(query)}&page=${page}`),
  ) as Promise<SearchMediaPage>

export const attachFile = withStats((path: string, params?: AttachParams): Promise<AttachResponse> => {
  const body: { path: string; fg_path?: string; address?: string; line?: number } = { path }
  if (params?.fgPath !== undefined) body.fg_path = params.fgPath
  if (params?.address !== undefined) body.address = params.address
  if (params?.line !== undefined) body.line = params.line
  return post(projectPath('/attach'), body) as Promise<AttachResponse>
})

async function postFormData(path: string, body: FormData): Promise<unknown> {
  const r = await fetch(path, { method: 'POST', body })
  if (!r.ok) throw new Error(await errorDetail(r))
  return r.json()
}

export interface UploadMountFileResponse {
  status: string
  path?: string
  detail?: string
}

export const uploadMountFile = withStats((dir: string, file: File): Promise<UploadMountFileResponse> => {
  const form = new FormData()
  form.append('dir', dir)
  form.append('file', file)
  return postFormData(projectPath('/mount/upload'), form) as Promise<UploadMountFileResponse>
})

export interface DeleteMountRefsFile {
  file: string
  line_numbers: number[]
}

export interface DeleteMountConfirmRequired {
  status: 'confirm_required'
  path: string
  refs: DeleteMountRefsFile[]
}

export interface DeleteMountOk {
  status: 'ok'
  path: string
  refs_cleaned?: number
}

export type DeleteMountPathResponse =
  | DeleteMountConfirmRequired
  | DeleteMountOk
  | { status: 'error'; detail?: string }

export const deleteMountPath = withStats((path: string): Promise<DeleteMountPathResponse> =>
  del(projectPath(`/mount/file/${path}`)) as Promise<DeleteMountPathResponse>
)

export const deleteMountPathConfirmed = withStats(
  (path: string): Promise<DeleteMountOk> =>
    del(projectPath(`/mount/file/${encodeURIComponent(path)}?confirmed=true`)) as Promise<DeleteMountOk>
)

export interface MoveMountFileResponse {
  status: string
  path?: string
  detail?: string
  refs_updated?: number
}

export const moveMountFile = (src: string, dst: string): Promise<MoveMountFileResponse> =>
  patch(projectPath(`/mount/file/${src}`), { to: dst }) as Promise<MoveMountFileResponse>

export function getMountPreviewPath(path: string): string {
  return projectPath(`/mount/preview/${path}`)
}

/** Flat metadata for a mount file: reserved path-derived keys + sidecar keys. */
export interface MountMetadata {
  relative_path: string
  name: string
  extension: string
  type: string
  [key: string]: unknown
}

export const getMountMetadata = (path: string): Promise<MountMetadata> =>
  get(projectPath(`/mount/metadata/${path}`)) as Promise<MountMetadata>

export const updateMountMetadata = withStats(
  (path: string, metadata: Record<string, unknown>): Promise<MountMetadata> =>
    put(projectPath(`/mount/metadata/${path}`), { metadata }) as Promise<MountMetadata>
)

export interface DeleteMountMetadataResponse {
  status: string
  path: string
}

export const deleteMountMetadata = withStats(
  (path: string): Promise<DeleteMountMetadataResponse> =>
    del(projectPath(`/mount/metadata/${path}`)) as Promise<DeleteMountMetadataResponse>
)

export const getNodeAddresses = async (): Promise<string[]> => {
  const tree = await getTree()
  function flatten(nodes: TreeNode[]): string[] {
    return nodes.flatMap((n) => [n.address, ...flatten(n.children)])
  }
  return flatten(tree)
}

// ---- Visual novel playback + TTS ----

export interface PlaybackTextItem {
  type: 'text'
  id: string
  line: number
  text: string
  /**
   * True when this line was produced by an AI operator; false for user-authored text.
   * Newer backends always send this; default to `true` when missing to preserve legacy styling.
   */
  ai_gen?: boolean
  /** Present when the node has TTS cache mode enabled. */
  tts_cached?: boolean
}

export interface PlaybackImageItem {
  type: 'image'
  line: number
  alt: string
  url: string
}

export interface PlaybackVideoItem {
  type: 'video'
  line: number
  alt: string
  url: string
}

/** Background+foreground composite scene (see `attach.build_layered_embed`). */
export interface PlaybackLayeredItem {
  type: 'layered'
  line: number
  bg_url: string
  bg_alt: string
  fg_url: string
  fg_alt: string
}

export interface PlaybackChatSession {
  ai_label?: string
  human_label?: string
}

export type PlaybackItem =
  | PlaybackTextItem
  | PlaybackImageItem
  | PlaybackVideoItem
  | PlaybackLayeredItem

/** Standalone scene layer in VN playback (image/video markdown or a composite embed). */
export function isVNBackdropItem(
  it: PlaybackItem,
): it is PlaybackImageItem | PlaybackVideoItem | PlaybackLayeredItem {
  return it.type === 'image' || it.type === 'video' || it.type === 'layered'
}

export interface PlaybackResponse {
  address: string
  tts_enabled: boolean
  items: PlaybackItem[]
  chat_session?: PlaybackChatSession
}

export const getPlayback = (addr: string): Promise<PlaybackResponse> =>
  get(projectPath(`/narrative/node/${addr}/playback`)) as Promise<PlaybackResponse>

export type TtsRenderStatus = 'ready' | 'started' | 'rendering'

export async function postTtsRender(
  addr: string,
  params: { line: number; chunk_id: string; voice_id?: string; model_id?: string }
): Promise<{ status: TtsRenderStatus }> {
  const q = new URLSearchParams({
    line: String(params.line),
    chunk_id: params.chunk_id,
  })
  if (params.voice_id) q.set('voice_id', params.voice_id)
  if (params.model_id) q.set('model_id', params.model_id)
  const path = projectPath(`/narrative/node/${addr}/tts/render?${q.toString()}`)
  const r = await fetch(path, { method: 'POST' })
  if (!r.ok) throw new Error(await errorDetail(r))
  return (await r.json()) as { status: TtsRenderStatus }
}

export type TtsChunkSsePayload =
  | { type: 'start'; content_type: string; from_cache: boolean }
  | { type: 'audio'; b64: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

export class TtsStreamBusyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'TtsStreamBusyError'
  }
}

/**
 * GET narrative TTS chunk as SSE; yields parsed JSON payloads from each `data:` line.
 * Throws `TtsStreamBusyError` when another project stream holds the lock (409).
 */
export async function* streamTtsChunkEvents(
  addr: string,
  params: { line: number; chunk_id: string; voice_id?: string; model_id?: string }
): AsyncGenerator<TtsChunkSsePayload> {
  const q = new URLSearchParams({
    line: String(params.line),
    chunk_id: params.chunk_id,
  })
  if (params.voice_id) q.set('voice_id', params.voice_id)
  if (params.model_id) q.set('model_id', params.model_id)
  const url = projectPath(`/narrative/node/${addr}/tts?${q.toString()}`)
  const r = await fetch(url)
  if (r.status === 409) {
    throw new TtsStreamBusyError(await errorDetail(r))
  }
  if (!r.ok) throw new Error(await errorDetail(r))
  const body = r.body
  if (body === null) throw new Error('No response body')
  const { parseSSEFromStream } = await import('./sse')
  for await (const event of parseSSEFromStream(body)) {
    yield JSON.parse(event.data) as TtsChunkSsePayload
  }
}

export type FetchTtsChunkBlobOptions = {
  /** Runs once after the first `audio` SSE frame arrives (generation may still be in progress). */
  onFirstAudioChunk?: () => void
}

/** Decode SSE audio frames into a single `Blob` suitable for `URL.createObjectURL`. */
export async function fetchTtsChunkAsBlob(
  addr: string,
  params: { line: number; chunk_id: string; voice_id?: string; model_id?: string },
  options?: FetchTtsChunkBlobOptions
): Promise<{ blob: Blob; contentType: string; fromCache: boolean }> {
  let contentType = 'audio/mpeg'
  let fromCache = false
  const chunks: Uint8Array[] = []
  let firstAudioNotified = false
  for await (const ev of streamTtsChunkEvents(addr, params)) {
    if (ev.type === 'start') {
      contentType = ev.content_type
      fromCache = ev.from_cache
    } else if (ev.type === 'audio') {
      if (!firstAudioNotified) {
        firstAudioNotified = true
        options?.onFirstAudioChunk?.()
      }
      const bin = atob(ev.b64)
      const u = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i)
      chunks.push(u)
    } else if (ev.type === 'error') {
      throw new Error(ev.message)
    }
  }
  const total = chunks.reduce((n, c) => n + c.length, 0)
  const merged = new Uint8Array(total)
  let o = 0
  for (const c of chunks) {
    merged.set(c, o)
    o += c.length
  }
  return { blob: new Blob([merged], { type: contentType }), contentType, fromCache }
}
