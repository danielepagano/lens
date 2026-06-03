import { isVNBackdropItem, type PlaybackItem } from '../services/api'

export type VnChunkMediaKind = 'none' | 'inherited' | 'current'

/**
 * Whether the scene image for this text beat is paired with the preceding playback item,
 * inherited from an earlier image line, or absent.
 */
export function classifyVnTextChunkMedia(
  items: PlaybackItem[],
  textBeatIndex: number
): { kind: VnChunkMediaKind; pairingImageLine?: number } {
  if (textBeatIndex < 0 || textBeatIndex >= items.length) return { kind: 'none' }
  const prev = textBeatIndex > 0 ? items[textBeatIndex - 1] : null
  if (prev && isVNBackdropItem(prev)) {
    return { kind: 'current', pairingImageLine: prev.line }
  }
  for (let i = textBeatIndex - 1; i >= 0; i--) {
    const it = items[i]
    if (it && isVNBackdropItem(it)) {
      return { kind: 'inherited', pairingImageLine: it.line }
    }
  }
  return { kind: 'none' }
}

/**
 * Playback item indices that are one Scene navigation step. Standalone images paired with
 * following text are folded into the text step; orphan images (no following text) are steps.
 */
export function vnNavigableIndices(items: PlaybackItem[]): number[] {
  const out: number[] = []
  for (let i = 0; i < items.length; i++) {
    const it = items[i]!
    if (it.type === 'text') {
      out.push(i)
      continue
    }
    if (isVNBackdropItem(it)) {
      const next = items[i + 1]
      if (next?.type !== 'text') {
        out.push(i)
      }
    }
  }
  return out
}

export function vnLogicalStepCount(items: PlaybackItem[], cursorCliSlot: boolean): number {
  const n = vnNavigableIndices(items).length
  return n + (cursorCliSlot ? 1 : 0)
}

/** Map logical Scene step → raw playback index, or `items.length` for the virtual CLI beat. */
export function logicalStepToPlaybackIndex(
  items: PlaybackItem[],
  logicalStep: number,
  cursorCliSlot: boolean
): number {
  const nav = vnNavigableIndices(items)
  if (items.length === 0) return 0
  const maxLogical = Math.max(vnLogicalStepCount(items, cursorCliSlot) - 1, 0)
  const s = Math.min(Math.max(logicalStep, 0), maxLogical)
  if (s >= nav.length) {
    return items.length
  }
  return nav[s]!
}

/** Map raw playback index (or virtual `items.length`) → logical step. */
export function playbackIndexToLogicalStep(items: PlaybackItem[], playbackIx: number): number {
  const nav = vnNavigableIndices(items)
  if (nav.length === 0) return 0
  if (playbackIx >= items.length) {
    return nav.length
  }
  const it = items[playbackIx]
  if (it?.type === 'text') {
    const pos = nav.indexOf(playbackIx)
    if (pos >= 0) return pos
  } else if (it && isVNBackdropItem(it)) {
    const next = items[playbackIx + 1]
    if (next?.type === 'text') {
      const pos = nav.indexOf(playbackIx + 1)
      if (pos >= 0) return pos
    } else {
      const pos = nav.indexOf(playbackIx)
      if (pos >= 0) return pos
    }
  }
  let best = 0
  for (let i = 0; i < nav.length; i++) {
    if (nav[i]! <= playbackIx) best = i
  }
  return best
}

/** Convert legacy session / old raw `vn_i` values to a logical step. */
export function legacyRawPlaybackIndexToLogicalStep(items: PlaybackItem[], rawIx: number): number {
  if (items.length === 0) return 0
  if (rawIx < 0) return 0
  if (rawIx >= items.length) {
    return vnNavigableIndices(items).length
  }
  return playbackIndexToLogicalStep(items, rawIx)
}

export function navigateVnLogicalStep(
  items: PlaybackItem[],
  logicalStep: number,
  delta: -1 | 1,
  cursorCliSlot: boolean
): number {
  const maxStep = Math.max(vnLogicalStepCount(items, cursorCliSlot) - 1, 0)
  return Math.min(Math.max(logicalStep + delta, 0), maxStep)
}

/** Logical step that shows the given TTS text chunk id. */
export function playbackLogicalStepForTextChunkId(items: PlaybackItem[], chunkId: string): number | null {
  const tIx = items.findIndex((it) => it.type === 'text' && it.id === chunkId)
  if (tIx < 0) return null
  const nav = vnNavigableIndices(items)
  const pos = nav.indexOf(tIx)
  return pos >= 0 ? pos : null
}

export function followingTextAfterImage(items: PlaybackItem[], imageIndex: number): PlaybackItem | null {
  const cur = items[imageIndex]
  if (!cur || !isVNBackdropItem(cur)) return null
  const n = items[imageIndex + 1]
  return n?.type === 'text' ? n : null
}
