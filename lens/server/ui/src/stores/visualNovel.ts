import { writable } from 'svelte/store'
import type { PlaybackResponse } from '../services/api'

export type { VnTtsSettings } from '../utils/vnTypes'

export const vnPlayback = writable<PlaybackResponse | null>(null)

/** After TTS synthesis, mark the text chunk cached so Scene UI and prefetch stay in sync. */
export function markVnPlaybackChunkTtsCached(chunkId: string): void {
  vnPlayback.update((data) => {
    if (!data) return data
    const items = data.items.map((it) =>
      it.type === 'text' && it.id === chunkId ? { ...it, tts_cached: true } : it
    )
    return { ...data, items }
  })
}
export const vnLoading = writable(false)
export const vnError = writable<string | null>(null)
/** Full-screen image exploration (minimal chrome). */
export const vnImageExplore = writable(false)
/** Object-fit step when not in explore mode: cover → contain → raw (none + scroll). */
export const vnImageFitStep = writable(0)

/** Item count from last successful `getPlayback` (for TopBar progress). */
export const vnPlaybackItemCount = writable(0)

/** Bumped after attach/replace from the media carousel so VN reloads playback for the same node. */
export const vnPlaybackRefreshTrigger = writable(0)

/** When set before opening the carousel, `getPlayback` restores this text chunk for the same node address. */
export const vnPlaybackAnchor = writable<{ address: string; chunkId: string } | null>(null)

/** Set before `/play` or `/chat` from the Scene CLI beat; consumed in `handleCliDone` to refetch playback. */
export const vnCursorCliOpSnapshot = writable<{
  address: string
  itemCount: number
  lastTextId: string | null
} | null>(null)

/** True when hash has `vn=1` for the current project/path usage in App. */
export function vnModeFromParsed(
  parsed: { vn: boolean; path: string },
  projectSlug: string | null,
  currentAddress: string | null
): boolean {
  if (!parsed.vn || !projectSlug || !currentAddress) return false
  return parsed.path === currentAddress
}
