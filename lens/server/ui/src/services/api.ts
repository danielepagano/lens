async function get(path: string): Promise<unknown> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`)
  return r.json()
}

async function post(path: string, body: unknown): Promise<unknown> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await errorDetail(r))
  return r.json()
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
  available_llms: string[]
  has_mount: boolean
  active_session_operator: string | null
  transaction: TransactionState | null
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
}

export interface NodeData {
  address: string
  content: string
  children: string[]
}

export const getStats = (): Promise<Stats> => get('/stats') as Promise<Stats>
export const getTree = (): Promise<TreeNode[]> =>
  get('/narrative/tree') as Promise<TreeNode[]>
export const getNode = (addr: string): Promise<NodeData> =>
  get(`/narrative/node/${addr}`) as Promise<NodeData>
export const setActiveNarrative = withStats((slug: string): Promise<{ active: string }> =>
  post('/narrative/narratives/active', { narrative: slug }) as Promise<{
    active: string
  }>
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
  const r = await fetch('/stream/cancel', { method: 'POST' })
  if (!r.ok) throw new Error(`HTTP ${r.status}: /stream/cancel`)
}

// ---- Operator streaming API ----

export interface OperatorTargetEvent {
  type: 'target'
  node: string
}

export interface OperatorTokenEvent {
  type: 'token'
  text: string
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
}

export type OperatorEvent =
  | OperatorTargetEvent
  | OperatorTokenEvent
  | OperatorDoneEvent
  | OperatorErrorEvent
  | OperatorProgressEvent

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
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  llm_id?: string
  retry?: boolean
}

export const runWrite = (
  params: WriteParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/write', params, onEvent)

export interface WriteManualResult {
  status: string
  node: string
}

export const runWriteManual = withStats((
  params: { text: string }
): Promise<WriteManualResult> =>
  post('/operator/write/manual', params) as Promise<WriteManualResult>
)

export interface PlayParams {
  prompt?: string
  module_id?: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
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
  runStreamingOp('/operator/play', params, onEvent)

export interface DesignParams {
  prompt?: string
  module_id?: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  retry?: boolean
  end?: boolean
  slug?: string
}

export const runDesign = (
  params: DesignParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/design', params, onEvent)

export interface AdvanceParams {
  days?: number
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  retry?: boolean
  feedback?: string
  end?: boolean
}

export const runAdvance = (
  params: AdvanceParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/advance', params, onEvent)

export interface EditParams {
  address: string
  start_line: number
  end_line: number
  prompt?: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  retry?: boolean
  replace?: boolean
  replacement?: string
}

export const runEdit = (
  params: EditParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/edit', params, onEvent)

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
  post('/operator/section/start', params) as Promise<SectionStartResult>
)

export interface SectionEndParams {
  llm_id?: string
}

export const runSectionEnd = (
  params: SectionEndParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/section/end', params, onEvent)

export interface CollateParams {
  id: string
  address: string
  start_line: number
  end_line: number
  pins?: string[]
  unpins?: string[]
  llm_id?: string
}

export const runCollate = (
  params: CollateParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/collate', params, onEvent)

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
  return get(`/kb/tags${query ? '?' + query : ''}`) as Promise<string[]>
}

export const getKbItems = (params?: { type?: string; tags?: string }): Promise<KbItem[]> => {
  const qs = new URLSearchParams()
  if (params?.type) qs.set('type', params.type)
  if (params?.tags) qs.set('tags', params.tags)
  const query = qs.toString()
  return get(`/kb/items${query ? '?' + query : ''}`) as Promise<KbItem[]>
}

export const getKbItem = (id: string): Promise<KbItemDetail> =>
  get(`/kb/item/${id}`) as Promise<KbItemDetail>

export const saveKbItem = withStats((id: string, content: string): Promise<{ id: string }> =>
  put(`/kb/item/${id}`, { content }) as Promise<{ id: string }>
)

export const createKbItem = withStats((
  id: string,
  content?: string,
  useTemplate?: boolean
): Promise<{ id: string; content: string }> =>
  post('/kb/items', { id, content, use_template: useTemplate ?? false }) as Promise<{
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
  patch(`/kb/item/${encodeURIComponent(id)}/tags`, body) as Promise<KbTagResponse>
)

export const deleteKbItem = withStats((id: string): Promise<{ id: string }> =>
  del(`/kb/item/${encodeURIComponent(id)}`) as Promise<{ id: string }>
)

export const renameKbItem = withStats((oldId: string, newId: string): Promise<KbRenameResponse> =>
  post('/kb/rename', { old_id: oldId, new_id: newId }) as Promise<KbRenameResponse>
)

export const copyKbItem = withStats((sourceId: string, targetId: string): Promise<KbCopyResponse> =>
  post('/kb/copy', { source_id: sourceId, target_id: targetId }) as Promise<KbCopyResponse>
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
  post('/kb/with-tag', { tags, ...options }) as Promise<KbWithTagResponse>

// ---- Transaction API ----

export interface TransactionActionResponse {
  status: 'ok' | 'error'
  detail?: string
  owner?: string | null
  is_mutation?: boolean
}

export const rollbackTransaction = withStats((): Promise<TransactionActionResponse> =>
  post('/rollback', {}) as Promise<TransactionActionResponse>
)

export const commitTransaction = withStats((): Promise<TransactionActionResponse> =>
  post('/commit', {}) as Promise<TransactionActionResponse>
)

export const checkpointTransaction = withStats((opts?: {
  message?: string
  push?: boolean
}): Promise<TransactionActionResponse> =>
  post('/checkpoint', opts ?? {}) as Promise<TransactionActionResponse>
)

export const refreshTransaction = withStats((opts?: {
  reset?: boolean
}): Promise<TransactionActionResponse> =>
  post('/refresh', opts ?? {}) as Promise<TransactionActionResponse>
)

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
}

export const getTxStatus = (): Promise<TxStatusResponse> =>
  get('/tx/status') as Promise<TxStatusResponse>

// ---- Narrative API ----

export type PinOperation = 'add' | 'remove' | 'block' | 'unblock'

export interface PinResponse {
  status: 'ok' | 'error'
  count?: number
  target?: string
  detail?: string
}

export const narrativePin = withStats((
  operation: PinOperation,
  ids: string[],
  node?: string
): Promise<PinResponse> =>
  post('/narrative/pin', { operation, ids, node }) as Promise<PinResponse>
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
  post('/narrative/rewind', params) as Promise<RewindResponse>
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
  post('/narrative/rename', params) as Promise<RenameNodeResponse>
)

export interface MountEntry {
  name: string
  is_dir: boolean
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
}

export const browseMountDir = (path = ''): Promise<MountEntry[]> =>
  get(`/mount/browse?path=${encodeURIComponent(path)}`) as Promise<MountEntry[]>

export const attachFile = withStats((path: string, params?: AttachParams): Promise<AttachResponse> => {
  const body: { path: string; address?: string; line?: number } = { path }
  if (params?.address !== undefined) body.address = params.address
  if (params?.line !== undefined) body.line = params.line
  return post('/attach', body) as Promise<AttachResponse>
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
  return postFormData('/mount/upload', form) as Promise<UploadMountFileResponse>
})

export interface DeleteMountPathResponse {
  status: string
  path?: string
  detail?: string
}

export const deleteMountPath = withStats((path: string): Promise<DeleteMountPathResponse> =>
  del(`/mount/file/${path}`) as Promise<DeleteMountPathResponse>
)

export const getNodeAddresses = async (): Promise<string[]> => {
  const tree = await getTree()
  function flatten(nodes: TreeNode[]): string[] {
    return nodes.flatMap((n) => [n.address, ...flatten(n.children)])
  }
  return flatten(tree)
}
