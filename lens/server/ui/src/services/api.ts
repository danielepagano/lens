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

export interface Stats {
  active_narrative: string | null
  narratives: string[]
  cursor: string | null
  has_pending: boolean
  pending_owner: string | null
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
export const getTransaction = (): Promise<TransactionState> =>
  get('/transaction') as Promise<TransactionState>
