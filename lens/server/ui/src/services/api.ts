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
  transaction: TransactionState | null
}

export interface DiffLine {
  kind: 'add' | 'remove'
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
  const r = await fetch('/cli/cancel', { method: 'POST' })
  if (!r.ok) throw new Error(`HTTP ${r.status}: /cli/cancel`)
}

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

export const getKbTypes = (): Promise<string[]> =>
  get('/kb/types') as Promise<string[]>

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
