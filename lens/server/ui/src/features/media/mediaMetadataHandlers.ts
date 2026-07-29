import { deleteMountMetadata, getMountMetadata, updateMountMetadata } from '../../services/api'
import type {
  MetadataFieldRow,
  MetadataKvItem,
  MetadataListItem,
  ReservedMetadata,
} from './mediaMetadataTypes'

export const RESERVED_KEYS = new Set(['relative_path', 'name', 'extension', 'type'])

let nextId = 0
function newId(prefix: string): string {
  nextId += 1
  return `${prefix}-${nextId}`
}

function stringifyScalar(v: unknown): string {
  if (v === null || v === undefined) return ''
  return String(v)
}

function createEmptyListItem(): MetadataListItem {
  return { id: newId('item'), value: '' }
}

function createEmptyKvItem(): MetadataKvItem {
  return { id: newId('kv'), key: '', value: '' }
}

function valueToRow(key: string, value: unknown): MetadataFieldRow {
  const id = newId('field')
  if (Array.isArray(value)) {
    return {
      id,
      key,
      kind: 'list',
      text: '',
      list: value.map((v): MetadataListItem => ({ id: newId('item'), value: stringifyScalar(v) })),
      kv: [],
    }
  }
  if (value !== null && typeof value === 'object') {
    return {
      id,
      key,
      kind: 'kv',
      text: '',
      list: [],
      kv: Object.entries(value as Record<string, unknown>).map(
        ([k, v]): MetadataKvItem => ({ id: newId('kv'), key: k, value: stringifyScalar(v) }),
      ),
    }
  }
  if (typeof value === 'number') {
    return { id, key, kind: 'number', text: String(value), list: [], kv: [] }
  }
  return { id, key, kind: 'text', text: stringifyScalar(value), list: [], kv: [] }
}

// ---------------------------------------------------------------------------
// Load / save
// ---------------------------------------------------------------------------

export interface LoadedMetadata {
  reserved: ReservedMetadata
  rows: MetadataFieldRow[]
  savedKeys: Set<string>
}

export async function loadMetadataRows(path: string): Promise<LoadedMetadata> {
  const meta = await getMountMetadata(path)
  const { relative_path, name, extension, type, ...extra } = meta
  const rows = Object.entries(extra).map(([key, value]) => valueToRow(key, value))
  return {
    reserved: { relative_path, name, extension, type },
    rows,
    savedKeys: new Set(Object.keys(extra)),
  }
}

function rowValue(row: MetadataFieldRow): unknown {
  switch (row.kind) {
    case 'number': {
      const trimmed = row.text.trim()
      const n = Number(trimmed)
      return trimmed !== '' && Number.isFinite(n) ? n : row.text
    }
    case 'list':
      return row.list.map((item) => item.value)
    case 'kv': {
      const out: Record<string, string> = {}
      for (const item of row.kv) {
        const k = item.key.trim()
        if (!k) continue
        out[k] = item.value
      }
      return out
    }
    default:
      return row.text
  }
}

export function rowsToExtra(rows: MetadataFieldRow[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (!key || RESERVED_KEYS.has(key)) continue
    out[key] = rowValue(row)
  }
  return out
}

/**
 * Persist the current field rows for `path`.
 *
 * `PUT /mount/metadata` only merges keys in — it never removes one. So when
 * a key present in `savedKeys` is no longer in the computed extra dict
 * (deleted row, or a row's key was renamed), the sidecar is wiped first and
 * then re-merged with whatever remains.
 */
export async function saveMetadataRows(
  path: string,
  rows: MetadataFieldRow[],
  savedKeys: Set<string>,
): Promise<Set<string>> {
  const extra = rowsToExtra(rows)
  const newKeys = new Set(Object.keys(extra))

  let removedKey = false
  for (const k of savedKeys) {
    if (!newKeys.has(k)) {
      removedKey = true
      break
    }
  }

  if (removedKey) {
    await deleteMountMetadata(path)
  }
  if (newKeys.size > 0) {
    try {
      await updateMountMetadata(path, extra)
    } catch (e) {
      // The wipe above already landed — retrying is safe (delete is a no-op
      // the second time) and will re-send every current field, so make that
      // explicit rather than leaving the user to guess what state it's in.
      const msg = e instanceof Error ? e.message : String(e)
      throw new Error(
        removedKey
          ? `Cleared the old fields but failed to save the new ones (${msg}). Click Save again to retry.`
          : msg,
      )
    }
  }
  return newKeys
}

// ---------------------------------------------------------------------------
// Pure row/item mutation helpers — callers always reassign `rows = fn(rows, …)`
// so Svelte's reactivity sees a fresh top-level array/object every time.
// ---------------------------------------------------------------------------

export function addRow(rows: MetadataFieldRow[]): MetadataFieldRow[] {
  return [...rows, { id: newId('field'), key: '', kind: 'text', text: '', list: [], kv: [] }]
}

export function removeRow(rows: MetadataFieldRow[], id: string): MetadataFieldRow[] {
  return rows.filter((r) => r.id !== id)
}

export function mapRow(
  rows: MetadataFieldRow[],
  id: string,
  fn: (row: MetadataFieldRow) => MetadataFieldRow,
): MetadataFieldRow[] {
  return rows.map((r) => (r.id === id ? fn(r) : r))
}

export function resetRowForKind(
  row: MetadataFieldRow,
  kind: MetadataFieldRow['kind'],
): MetadataFieldRow {
  if (kind === row.kind) return row
  return {
    id: row.id,
    key: row.key,
    kind,
    text: '',
    list: kind === 'list' ? [createEmptyListItem()] : [],
    kv: kind === 'kv' ? [createEmptyKvItem()] : [],
  }
}

export function addListItem(row: MetadataFieldRow): MetadataFieldRow {
  return { ...row, list: [...row.list, createEmptyListItem()] }
}

export function removeListItem(row: MetadataFieldRow, itemId: string): MetadataFieldRow {
  return { ...row, list: row.list.filter((i) => i.id !== itemId) }
}

export function mapListItem(
  row: MetadataFieldRow,
  itemId: string,
  fn: (item: MetadataListItem) => MetadataListItem,
): MetadataFieldRow {
  return { ...row, list: row.list.map((i) => (i.id === itemId ? fn(i) : i)) }
}

export function addKvItem(row: MetadataFieldRow): MetadataFieldRow {
  return { ...row, kv: [...row.kv, createEmptyKvItem()] }
}

export function removeKvItem(row: MetadataFieldRow, itemId: string): MetadataFieldRow {
  return { ...row, kv: row.kv.filter((i) => i.id !== itemId) }
}

export function mapKvItem(
  row: MetadataFieldRow,
  itemId: string,
  fn: (item: MetadataKvItem) => MetadataKvItem,
): MetadataFieldRow {
  return { ...row, kv: row.kv.map((i) => (i.id === itemId ? fn(i) : i)) }
}
