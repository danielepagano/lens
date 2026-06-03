import type { VnTtsSettings } from './vnTypes'
import { DEFAULT_VN_TTS } from './vnTypes'

const LS_KEY = 'lens.vn.session'

/** @deprecated Stored raw `PlaybackItem` index; migrated on load to {@link VnSessionBlobV2}. */
export interface VnSessionBlobV1 {
  version: 1
  projectSlug: string
  nodeAddress: string
  itemIndex: number
  settings: VnTtsSettings
}

export interface VnSessionBlobV2 {
  version: 2
  projectSlug: string
  nodeAddress: string  /** User-visible Scene step (text beat or orphan image), not raw playback index. */
  logicalStep: number
  settings: VnTtsSettings
}

export type VnSessionBlob = VnSessionBlobV1 | VnSessionBlobV2

function normalizeSettings(raw: unknown): VnTtsSettings {
  if (raw && typeof raw === 'object' && 'speak' in raw && typeof (raw as VnTtsSettings).speak === 'boolean') {
    const s = raw as VnTtsSettings
    return {
      speak: s.speak,
      autoAdvance: Boolean(s.autoAdvance),
      renderNew: Boolean(s.renderNew),
    }
  }
  return { ...DEFAULT_VN_TTS }
}

export function readVnSession(): VnSessionBlob | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return null
    const o = JSON.parse(raw) as Record<string, unknown>
    if (o.version !== 1 && o.version !== 2) return null
    if (typeof o.projectSlug !== 'string' || typeof o.nodeAddress !== 'string') return null

    const settings = normalizeSettings(o.settings)

    if (o.version === 2) {
      const logicalStep = typeof o.logicalStep === 'number' && o.logicalStep >= 0 ? o.logicalStep : 0
      return {
        version: 2,
        projectSlug: o.projectSlug,
        nodeAddress: o.nodeAddress,
        logicalStep,
        settings,
      }
    }

    const itemIndex = typeof o.itemIndex === 'number' && o.itemIndex >= 0 ? o.itemIndex : 0
    return {
      version: 1,
      projectSlug: o.projectSlug,
      nodeAddress: o.nodeAddress,
      itemIndex,
      settings,
    }
  } catch {
    return null
  }
}

export function writeVnSession(blob: VnSessionBlob): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(blob))
  } catch {
    /* quota / private mode */
  }
}
