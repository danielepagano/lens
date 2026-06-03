import type { ParsedAppHash } from './appHash'
import type { VnTtsSettings } from './vnTypes'
import { DEFAULT_VN_TTS } from './vnTypes'
import { readVnSession, writeVnSession, type VnSessionBlobV2 } from './vnSessionStorage'
import { buildAppHash } from './appHash'
import { urlHash } from '../stores/urlHash'

/** Set `window.location.hash` and sync `urlHash` so routing-derived UI updates in the same turn (hashchange may be async). */
function commitLocationHash(hashWithLeadingHash: string): void {
  window.location.hash = hashWithLeadingHash
  urlHash.set(window.location.hash)
}

/**
 * Scene step index from URL (`vn_i`) or session. This is a **logical** step (dialogue / orphan-image
 * beat), not a raw `PlaybackItem` index — see `vnNavigableIndices` in `vnPlaybackNav.ts`.
 */
export function resolveVisualNovelIndex(
  parsed: ParsedAppHash,
  slug: string,
  nodeAddress: string
): number {
  if (parsed.vn_i_explicit) return parsed.vn_i
  const blob = readVnSession()
  if (blob && blob.projectSlug === slug && blob.nodeAddress === nodeAddress) {
    if (blob.version === 2) return blob.logicalStep
    return blob.itemIndex
  }
  return 0
}

export function resolveVisualNovelTtsSettings(parsed: ParsedAppHash): VnTtsSettings {
  if (parsed.vnTtsFromUrl) return parsed.vnTts
  const blob = readVnSession()
  return blob?.settings ? { ...blob.settings } : { ...DEFAULT_VN_TTS }
}

/** Visual Novel hash always includes `vn_i` so index 0 is unambiguous vs omitted param. */
export function setVisualNovelHash(
  slug: string,
  narrativePath: string,
  logicalStep: number,
  vnTts: VnTtsSettings
): void {
  const params = new URLSearchParams()
  params.set('vn', '1')
  params.set('vn_i', String(logicalStep))
  params.set('vn_spk', vnTts.speak ? '1' : '0')
  if (vnTts.speak) {
    if (vnTts.autoAdvance) params.set('vn_aa', '1')
    if (vnTts.renderNew) params.set('vn_rdr', '1')
  }
  const base = narrativePath ? `${slug}/${narrativePath}` : slug
  commitLocationHash(`#${base}?${params.toString()}`)
}

export function enterVisualNovel(slug: string, narrativePath: string): void {
  const blob = readVnSession()
  let logicalStep = 0
  let vnTts: VnTtsSettings = { ...DEFAULT_VN_TTS }
  if (blob && blob.projectSlug === slug && blob.nodeAddress === narrativePath) {
    vnTts = { ...blob.settings }
    logicalStep = blob.version === 2 ? blob.logicalStep : blob.itemIndex
  }
  setVisualNovelHash(slug, narrativePath, logicalStep, vnTts)
}

export function exitVisualNovel(
  slug: string,
  narrativePath: string,
  logicalStep: number,
  vnTts: VnTtsSettings
): void {
  const blob: VnSessionBlobV2 = {
    version: 2,
    projectSlug: slug,
    nodeAddress: narrativePath,
    logicalStep,
    settings: { ...vnTts },
  }
  writeVnSession(blob)
  commitLocationHash('#' + buildAppHash(slug, narrativePath, {}))
}
