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
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${path}`)
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

export class CliRunBusyError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message)
    this.name = 'CliRunBusyError'
  }
}

export interface Stats {
  active_narrative: string | null
  narratives: string[]
  cursor: string | null
  has_pending: boolean
  pending_owner: string | null
  dataset_name: string | null
  current_datasets: string[] | null
  kb_types: string[]
  kb_count: number
  effective_pins_at_cursor: string[] | null
  available_llms: string[]
  transaction: TransactionState | null
}

export interface DiffLine {
  kind: 'add' | 'remove' | 'context'
  text: string
  is_annotation: boolean
}

export interface DiffHunk {
  old_start: number
  new_start: number
  lines: DiffLine[]
}

export interface FileDiff {
  path: string
  address: string | null
  hunks: DiffHunk[]
}

export interface TransactionState {
  has_pending: boolean
  owner: string | null
  is_mutation: boolean
  files: FileDiff[]
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
export const getTree = (): Promise<TreeNode[]> => get('/tree') as Promise<TreeNode[]>
export const getNode = (addr: string): Promise<NodeData> =>
  get(`/node/${addr}`) as Promise<NodeData>
export const setActiveNarrative = (slug: string): Promise<{ active: string }> =>
  post('/narratives/active', { narrative: slug }) as Promise<{ active: string }>

export interface CliEventOut {
  type: 'out'
  text?: string
}
export interface CliEventErr {
  type: 'err'
  text?: string
}
export interface CliEventDone {
  type: 'done'
  exit_code?: number
}
export type CliEvent = CliEventOut | CliEventErr | CliEventDone

async function errorDetail(r: Response): Promise<string> {
  try {
    const data = (await r.json()) as { detail?: string }
    if (typeof data.detail === 'string') return data.detail
  } catch {
    /* ignore */
  }
  return `HTTP ${r.status}: ${r.url}`
}

export async function runCliStream(
  command: string,
  payload: string,
  onEvent: (event: CliEvent) => void
): Promise<{ exit_code: number }> {
  const r = await fetch('/cli/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, payload }),
  })
  if (r.status === 409 || r.status === 423) {
    throw new CliRunBusyError(await errorDetail(r), r.status)
  }
  if (!r.ok) throw new Error(await errorDetail(r))
  const body = r.body
  if (body === null) throw new Error('No response body')
  const { parseSSEFromStream } = await import('./sse')
  let exitCode = -1
  for await (const event of parseSSEFromStream(body)) {
    const parsed = JSON.parse(event.data) as CliEvent
    onEvent(parsed)
    if (parsed.type === 'done' && parsed.exit_code !== undefined) {
      exitCode = parsed.exit_code
    }
  }
  return { exit_code: exitCode }
}

export async function cancelCliRun(): Promise<void> {
  await cancelStream()
}

// ---- Unified stream cancel ----

export async function cancelStream(): Promise<void> {
  const r = await fetch('/stream/cancel', { method: 'POST' })
  if (!r.ok) throw new Error(`HTTP ${r.status}: /stream/cancel`)
}

// ---- Operator streaming API ----

export interface OperatorTokenEvent {
  type: 'token'
  text: string
  node: string
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

export type OperatorEvent = OperatorTokenEvent | OperatorDoneEvent | OperatorErrorEvent

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

export interface PlayParams {
  prompt: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
  retry?: boolean
  as_pc?: string
}

export const runPlay = (
  params: PlayParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/play', params, onEvent)

export interface DesignParams {
  id: string
  prompt?: string
  pins?: string[]
  unpins?: string[]
  llm_id?: string
}

export const runDesign = (
  params: DesignParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/design', params, onEvent)

export interface DesignEndResult {
  inserted: string[]
  updated: string[]
  errors: string[]
}

export const runDesignEnd = (): Promise<DesignEndResult> =>
  post('/operator/design/end', {}) as Promise<DesignEndResult>

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

export const runSectionStart = (
  params: SectionStartParams
): Promise<SectionStartResult> =>
  post('/operator/section/start', params) as Promise<SectionStartResult>

export interface SectionEndParams {
  llm_id?: string
}

export const runSectionEnd = (
  params: SectionEndParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/section/end', params, onEvent)

export interface SectionRangeParams {
  id: string
  address: string
  start_line: number
  end_line: number
  pins?: string[]
  unpins?: string[]
  llm_id?: string
}

export const runSectionRange = (
  params: SectionRangeParams,
  onEvent: (event: OperatorEvent) => void
): Promise<OperatorDoneEvent | OperatorErrorEvent> =>
  runStreamingOp('/operator/section/range', params, onEvent)

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

export const saveKbItem = (id: string, content: string): Promise<{ id: string }> =>
  put(`/kb/item/${id}`, { content }) as Promise<{ id: string }>

export const createKbItem = (
  id: string,
  content?: string,
  useTemplate?: boolean
): Promise<{ id: string; content: string }> =>
  post('/kb/items', { id, content, use_template: useTemplate ?? false }) as Promise<{
    id: string
    content: string
  }>

export interface KbWithTagResponse {
  ids: string[]
}

export const getKbWithTag = (tags: string[]): Promise<KbWithTagResponse> =>
  post('/kb/with-tag', { tags }) as Promise<KbWithTagResponse>

// ---- Transaction API ----

export interface TransactionActionResponse {
  status: 'ok' | 'error'
  detail?: string
  owner?: string | null
  is_mutation?: boolean
}

export const rollbackTransaction = (): Promise<TransactionActionResponse> =>
  post('/rollback', {}) as Promise<TransactionActionResponse>

export const commitTransaction = (): Promise<TransactionActionResponse> =>
  post('/commit', {}) as Promise<TransactionActionResponse>

export const checkpointTransaction = (opts?: {
  message?: string
  push?: boolean
}): Promise<TransactionActionResponse> =>
  post('/checkpoint', opts ?? {}) as Promise<TransactionActionResponse>

// ---- Narrative API ----

export type PinOperation = 'add' | 'remove' | 'block' | 'unblock'

export interface PinResponse {
  status: 'ok' | 'error'
  count?: number
  target?: string
  detail?: string
}

export const narrativePin = (
  operation: PinOperation,
  ids: string[],
  node?: string
): Promise<PinResponse> =>
  post('/narrative/pin', { operation, ids, node }) as Promise<PinResponse>

export const getNodeAddresses = async (): Promise<string[]> => {
  const tree = await getTree()
  function flatten(nodes: TreeNode[]): string[] {
    return nodes.flatMap((n) => [n.address, ...flatten(n.children)])
  }
  return flatten(tree)
}
