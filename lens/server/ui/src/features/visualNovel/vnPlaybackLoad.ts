import { get } from 'svelte/store'
import { currentProject } from '../../stores/project'
import { parsedHash } from '../../stores/parsedHash'
import { stats } from '../../stores/stats'
import {
  vnPlayback,
  vnLoading,
  vnError,
  vnPlaybackItemCount,
  vnPlaybackAnchor,
} from '../../stores/visualNovel'
import { getPlayback } from '../../services/api'
import {
  resolveVisualNovelTtsSettings,
  setVisualNovelHash,
} from '../../utils/vnNavigate'
import { vnCursorCliSlotEligible } from '../../utils/vnCursorCli'
import {
  playbackLogicalStepForTextChunkId,
  legacyRawPlaybackIndexToLogicalStep,
  vnLogicalStepCount,
} from '../../utils/vnPlaybackNav'
import { readVnSession, writeVnSession } from '../../utils/vnSessionStorage'

export async function runVnPlaybackLoad(addr: string): Promise<void> {
  const anchor = get(vnPlaybackAnchor)
  vnPlaybackAnchor.set(null)
  vnLoading.set(true)
  vnError.set(null)
  try {
    const data = await getPlayback(addr)
    if (!get(parsedHash).vn) return
    vnPlayback.set(data)
    const slug = get(currentProject)!
    const ph = get(parsedHash)
    const eligible = vnCursorCliSlotEligible(get(stats), addr, data.items)
    vnPlaybackItemCount.set(vnLogicalStepCount(data.items, eligible))
    const blob = readVnSession()
    let logicalStep: number
    if (anchor && anchor.address === addr) {
      logicalStep = playbackLogicalStepForTextChunkId(data.items, anchor.chunkId) ?? 0
    } else if (
      blob?.projectSlug === slug &&
      blob.nodeAddress === addr &&
      blob.version === 1
    ) {
      logicalStep = legacyRawPlaybackIndexToLogicalStep(data.items, blob.itemIndex)
    } else if (ph.vn_i_explicit) {
      logicalStep = ph.vn_i
    } else if (
      blob?.version === 2 &&
      blob.projectSlug === slug &&
      blob.nodeAddress === addr
    ) {
      logicalStep = blob.logicalStep
    } else {
      logicalStep = 0
    }
    if (data.items.length === 0) {
      logicalStep = 0
    } else {
      const maxLogical = Math.max(vnLogicalStepCount(data.items, eligible) - 1, 0)
      logicalStep = Math.min(Math.max(logicalStep, 0), maxLogical)
    }
    const tts = resolveVisualNovelTtsSettings(ph)
    setVisualNovelHash(slug, addr, logicalStep, tts)
    if (
      blob?.projectSlug === slug &&
      blob.nodeAddress === addr &&
      blob.version === 1
    ) {
      writeVnSession({
        version: 2,
        projectSlug: slug,
        nodeAddress: addr,
        logicalStep,
        settings: blob.settings,
      })
    }
  } catch (e) {
    vnError.set(e instanceof Error ? e.message : String(e))
    vnPlayback.set(null)
    vnPlaybackItemCount.set(0)
  } finally {
    vnLoading.set(false)
  }
}

export function vnPlaybackFetchKey(addr: string, refresh: number): string {
  return `${addr}\n${refresh}`
}
