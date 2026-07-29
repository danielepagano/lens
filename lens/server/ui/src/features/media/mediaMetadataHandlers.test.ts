import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { MetadataFieldRow } from './mediaMetadataTypes'

vi.mock('../../services/api', () => ({
  getMountMetadata: vi.fn(),
  updateMountMetadata: vi.fn(),
  deleteMountMetadata: vi.fn(),
}))

import { getMountMetadata, updateMountMetadata, deleteMountMetadata } from '../../services/api'
import {
  addKvItem,
  addListItem,
  addRow,
  loadMetadataRows,
  mapKvItem,
  mapListItem,
  mapRow,
  removeKvItem,
  removeListItem,
  removeRow,
  resetRowForKind,
  rowsToExtra,
  saveMetadataRows,
} from './mediaMetadataHandlers'

const mockGetMountMetadata = vi.mocked(getMountMetadata)
const mockUpdateMountMetadata = vi.mocked(updateMountMetadata)
const mockDeleteMountMetadata = vi.mocked(deleteMountMetadata)

function textRow(key: string, text: string): MetadataFieldRow {
  return { id: `row-${key}`, key, kind: 'text', text, list: [], kv: [] }
}

function numberRow(key: string, text: string): MetadataFieldRow {
  return { id: `row-${key}`, key, kind: 'number', text, list: [], kv: [] }
}

function listRow(key: string, values: string[]): MetadataFieldRow {
  return {
    id: `row-${key}`,
    key,
    kind: 'list',
    text: '',
    list: values.map((value, i) => ({ id: `item-${i}`, value })),
    kv: [],
  }
}

function kvRow(key: string, pairs: [string, string][]): MetadataFieldRow {
  return {
    id: `row-${key}`,
    key,
    kind: 'kv',
    text: '',
    list: [],
    kv: pairs.map(([k, value], i) => ({ id: `kv-${i}`, key: k, value })),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('rowsToExtra', () => {
  it('converts text/number/list/kv rows to a flat extra dict', () => {
    const rows = [
      textRow('character', 'amy'),
      numberRow('layer', '2'),
      listRow('tags', ['house', 'couch']),
      kvRow('expression', [['mood', 'happy']]),
    ]
    expect(rowsToExtra(rows)).toEqual({
      character: 'amy',
      layer: 2,
      tags: ['house', 'couch'],
      expression: { mood: 'happy' },
    })
  })

  it('skips rows with an empty or whitespace-only key', () => {
    expect(rowsToExtra([textRow('', 'x'), textRow('   ', 'y')])).toEqual({})
  })

  it('drops reserved keys silently, matching the backend contract', () => {
    const rows = [textRow('name', 'evil'), textRow('type', 'video'), textRow('ok', 'kept')]
    expect(rowsToExtra(rows)).toEqual({ ok: 'kept' })
  })

  it('falls back to the raw string when a number field is not a valid number', () => {
    expect(rowsToExtra([numberRow('n', 'not-a-number')])).toEqual({ n: 'not-a-number' })
  })

  it('trims whitespace before parsing a number', () => {
    expect(rowsToExtra([numberRow('n', '  12  ')])).toEqual({ n: 12 })
  })

  it('drops kv pairs with an empty key but keeps the row', () => {
    const rows = [kvRow('expression', [['', 'dropped'], ['mood', 'kept']])]
    expect(rowsToExtra(rows)).toEqual({ expression: { mood: 'kept' } })
  })
})

describe('loadMetadataRows', () => {
  it('splits reserved fields from extra and converts each extra value to a row', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'characters/amy.jpg',
      name: 'amy.jpg',
      extension: '.jpg',
      type: 'image',
      character: 'amy',
      layer: 2,
      tags: ['house', 'couch'],
      expression: { mood: 'happy' },
    })

    const result = await loadMetadataRows('characters/amy.jpg')

    expect(result.reserved).toEqual({
      relative_path: 'characters/amy.jpg',
      name: 'amy.jpg',
      extension: '.jpg',
      type: 'image',
    })
    expect(result.savedKeys).toEqual(new Set(['character', 'layer', 'tags', 'expression']))

    const byKey = Object.fromEntries(result.rows.map((r) => [r.key, r]))
    expect(byKey.character).toMatchObject({ kind: 'text', text: 'amy' })
    expect(byKey.layer).toMatchObject({ kind: 'number', text: '2' })
    expect(byKey.tags).toMatchObject({ kind: 'list', list: [{ value: 'house' }, { value: 'couch' }] })
    expect(byKey.expression).toMatchObject({ kind: 'kv', kv: [{ key: 'mood', value: 'happy' }] })
  })

  it('returns no rows when there is no sidecar', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'hero.jpg',
      name: 'hero.jpg',
      extension: '.jpg',
      type: 'image',
    })
    const result = await loadMetadataRows('hero.jpg')
    expect(result.rows).toEqual([])
    expect(result.savedKeys.size).toBe(0)
    expect(result.compositeValue).toBeNull()
  })

  it('extracts a valid composite role for images and excludes it from the generic rows', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/forest.jpg',
      name: 'forest.jpg',
      extension: '.jpg',
      type: 'image',
      composite: 'background',
      character: 'amy',
    })

    const result = await loadMetadataRows('bg/forest.jpg')

    expect(result.compositeValue).toBe('background')
    expect(result.rows.map((r) => r.key)).toEqual(['character'])
    // composite still counts as a saved key so removing it triggers the wipe-then-remerge save path
    expect(result.savedKeys).toEqual(new Set(['composite', 'character']))
  })

  it('normalizes an invalid composite value to null for images', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/forest.jpg',
      name: 'forest.jpg',
      extension: '.jpg',
      type: 'image',
      composite: 'sideways',
    })

    const result = await loadMetadataRows('bg/forest.jpg')

    expect(result.compositeValue).toBeNull()
    expect(result.rows).toEqual([])
  })

  it('leaves composite as a regular row for non-image types', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'clip.mp4',
      name: 'clip.mp4',
      extension: '.mp4',
      type: 'video',
      composite: 'background',
    })

    const result = await loadMetadataRows('clip.mp4')

    expect(result.compositeValue).toBeUndefined()
    expect(result.rows.map((r) => r.key)).toEqual(['composite'])
  })
})

describe('saveMetadataRows', () => {
  it('only PUTs when no key was removed', async () => {
    mockUpdateMountMetadata.mockResolvedValue({
      relative_path: 'hero.jpg', name: 'hero.jpg', extension: '.jpg', type: 'image',
    })
    const rows = [textRow('character', 'amy')]
    const newKeys = await saveMetadataRows('hero.jpg', rows, new Set())

    expect(mockDeleteMountMetadata).not.toHaveBeenCalled()
    expect(mockUpdateMountMetadata).toHaveBeenCalledWith('hero.jpg', { character: 'amy' })
    expect(newKeys).toEqual(new Set(['character']))
  })

  it('DELETEs then PUTs when a key was removed but others remain', async () => {
    mockUpdateMountMetadata.mockResolvedValue({
      relative_path: 'hero.jpg', name: 'hero.jpg', extension: '.jpg', type: 'image',
    })
    const rows = [textRow('character', 'amy')]
    const savedKeys = new Set(['character', 'expression'])

    await saveMetadataRows('hero.jpg', rows, savedKeys)

    expect(mockDeleteMountMetadata).toHaveBeenCalledWith('hero.jpg')
    expect(mockUpdateMountMetadata).toHaveBeenCalledWith('hero.jpg', { character: 'amy' })
  })

  it('only DELETEs (no PUT) when every field was removed', async () => {
    const savedKeys = new Set(['character'])
    const newKeys = await saveMetadataRows('hero.jpg', [], savedKeys)

    expect(mockDeleteMountMetadata).toHaveBeenCalledWith('hero.jpg')
    expect(mockUpdateMountMetadata).not.toHaveBeenCalled()
    expect(newKeys).toEqual(new Set())
  })

  it('surfaces a retry-safe error when DELETE succeeds but the follow-up PUT fails', async () => {
    mockUpdateMountMetadata.mockRejectedValue(new Error('network blip'))
    const rows = [textRow('character', 'amy')]
    const savedKeys = new Set(['character', 'expression'])

    await expect(saveMetadataRows('hero.jpg', rows, savedKeys)).rejects.toThrow(
      /Cleared the old fields but failed to save the new ones \(network blip\)\. Click Save again to retry\./,
    )
  })

  it('passes the raw error through unchanged when nothing was deleted first', async () => {
    mockUpdateMountMetadata.mockRejectedValue(new Error('network blip'))
    const rows = [textRow('character', 'amy')]

    await expect(saveMetadataRows('hero.jpg', rows, new Set())).rejects.toThrow('network blip')
  })

  it('merges a set composite value into the saved extra dict', async () => {
    mockUpdateMountMetadata.mockResolvedValue({
      relative_path: 'bg.jpg', name: 'bg.jpg', extension: '.jpg', type: 'image',
    })
    const rows = [textRow('character', 'amy')]

    await saveMetadataRows('bg.jpg', rows, new Set(), 'background')

    expect(mockUpdateMountMetadata).toHaveBeenCalledWith('bg.jpg', {
      character: 'amy',
      composite: 'background',
    })
  })

  it('wipes composite when set back to null (unset)', async () => {
    const savedKeys = new Set(['composite'])

    const newKeys = await saveMetadataRows('bg.jpg', [], savedKeys, null)

    expect(mockDeleteMountMetadata).toHaveBeenCalledWith('bg.jpg')
    expect(mockUpdateMountMetadata).not.toHaveBeenCalled()
    expect(newKeys).toEqual(new Set())
  })

  it('leaves composite untouched when compositeValue is undefined (non-image types)', async () => {
    mockUpdateMountMetadata.mockResolvedValue({
      relative_path: 'clip.mp4', name: 'clip.mp4', extension: '.mp4', type: 'video',
    })
    const rows = [textRow('composite', 'background')]

    await saveMetadataRows('clip.mp4', rows, new Set())

    expect(mockUpdateMountMetadata).toHaveBeenCalledWith('clip.mp4', { composite: 'background' })
  })
})

describe('pure row/item mutation helpers', () => {
  it('addRow appends an empty text row', () => {
    const rows = addRow([textRow('a', '1')])
    expect(rows).toHaveLength(2)
    expect(rows[1]).toMatchObject({ key: '', kind: 'text', text: '' })
  })

  it('removeRow drops only the matching row', () => {
    const rows = [textRow('a', '1'), textRow('b', '2')]
    const result = removeRow(rows, 'row-a')
    expect(result.map((r) => r.key)).toEqual(['b'])
  })

  it('mapRow updates only the matching row, leaving others untouched', () => {
    const original = [textRow('a', '1'), textRow('b', '2')]
    const result = mapRow(original, 'row-a', (r) => ({ ...r, text: 'changed' }))
    expect(result[0]?.text).toBe('changed')
    expect(result[1]).toBe(original[1]) // untouched row is the same reference
  })

  it('resetRowForKind is a no-op when the kind is unchanged', () => {
    const row = textRow('a', '1')
    expect(resetRowForKind(row, 'text')).toBe(row)
  })

  it('resetRowForKind clears the value and seeds one empty item for list/kv', () => {
    const row = textRow('a', 'old value')
    const asList = resetRowForKind(row, 'list')
    expect(asList).toMatchObject({ kind: 'list', text: '' })
    expect(asList.list).toHaveLength(1)

    const asKv = resetRowForKind(row, 'kv')
    expect(asKv).toMatchObject({ kind: 'kv', text: '' })
    expect(asKv.kv).toHaveLength(1)
  })

  it('addListItem/removeListItem/mapListItem operate immutably', () => {
    const row = listRow('tags', ['house'])
    const added = addListItem(row)
    expect(added.list).toHaveLength(2)
    expect(row.list).toHaveLength(1) // original untouched

    const updated = mapListItem(added, added.list[1]!.id, (i) => ({ ...i, value: 'couch' }))
    expect(updated.list.map((i) => i.value)).toEqual(['house', 'couch'])

    const removed = removeListItem(updated, updated.list[0]!.id)
    expect(removed.list.map((i) => i.value)).toEqual(['couch'])
  })

  it('addKvItem/removeKvItem/mapKvItem operate immutably', () => {
    const row = kvRow('composite', [['type', 'subject']])
    const added = addKvItem(row)
    expect(added.kv).toHaveLength(2)
    expect(row.kv).toHaveLength(1) // original untouched

    const updated = mapKvItem(added, added.kv[1]!.id, (i) => ({ ...i, key: 'layer', value: '2' }))
    expect(updated.kv.map((i) => [i.key, i.value])).toEqual([['type', 'subject'], ['layer', '2']])

    const removed = removeKvItem(updated, updated.kv[0]!.id)
    expect(removed.kv.map((i) => i.key)).toEqual(['layer'])
  })
})
