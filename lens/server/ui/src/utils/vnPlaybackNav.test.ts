import { describe, expect, it } from 'vitest'
import {
  classifyVnTextChunkMedia,
  playbackLogicalStepForTextChunkId,
  vnNavigableIndices,
  logicalStepToPlaybackIndex,
  playbackIndexToLogicalStep,
  legacyRawPlaybackIndexToLogicalStep,
  navigateVnLogicalStep,
  vnLogicalStepCount,
} from './vnPlaybackNav'
import type { PlaybackItem } from '../services/api'

describe('classifyVnTextChunkMedia', () => {
  it('returns current when previous item is an image', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 't', line: 2, text: 'hi', tts_cached: undefined },
    ]
    expect(classifyVnTextChunkMedia(items, 1)).toEqual({
      kind: 'current',
      pairingImageLine: 1,
    })
  })

  it('returns inherited when an earlier image exists but previous item is text', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 'a', line: 2, text: 'one', tts_cached: undefined },
      { type: 'text', id: 'b', line: 2, text: 'two', tts_cached: undefined },
    ]
    expect(classifyVnTextChunkMedia(items, 2)).toEqual({
      kind: 'inherited',
      pairingImageLine: 1,
    })
  })

  it('returns none when there is no prior image', () => {
    const items: PlaybackItem[] = [
      { type: 'text', id: 'a', line: 1, text: 'one', tts_cached: undefined },
    ]
    expect(classifyVnTextChunkMedia(items, 0)).toEqual({ kind: 'none' })
  })
})

describe('vnNavigableIndices', () => {
  it('folds image+text into the text index only', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 't', line: 2, text: 'hi', tts_cached: undefined },
    ]
    expect(vnNavigableIndices(items)).toEqual([1])
  })

  it('keeps orphan image as its own step', () => {
    const items: PlaybackItem[] = [{ type: 'image', line: 1, alt: '', url: 'a.png' }]
    expect(vnNavigableIndices(items)).toEqual([0])
  })
})

describe('playbackLogicalStepForTextChunkId', () => {
  it('returns logical step for text after an image', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 'b', line: 2, text: 'hi', tts_cached: undefined },
    ]
    expect(playbackLogicalStepForTextChunkId(items, 'b')).toBe(0)
  })

  it('returns logical step for lone text', () => {
    const items: PlaybackItem[] = [
      { type: 'text', id: 'b', line: 2, text: 'hi', tts_cached: undefined },
    ]
    expect(playbackLogicalStepForTextChunkId(items, 'b')).toBe(0)
  })
})

describe('logical step mapping', () => {
  it('maps logical steps to playback indices for interleaved image+text', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 'a', line: 2, text: 'a', tts_cached: undefined },
      { type: 'image', line: 3, alt: '', url: 'b.png' },
      { type: 'text', id: 'b', line: 4, text: 'b', tts_cached: undefined },
    ]
    expect(logicalStepToPlaybackIndex(items, 0, false)).toBe(1)
    expect(logicalStepToPlaybackIndex(items, 1, false)).toBe(3)
    expect(playbackIndexToLogicalStep(items, 1)).toBe(0)
    expect(playbackIndexToLogicalStep(items, 3)).toBe(1)
  })

  it('legacy raw image index maps to same logical step as paired text', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 'b', line: 2, text: 'hi', tts_cached: undefined },
    ]
    expect(legacyRawPlaybackIndexToLogicalStep(items, 0)).toBe(0)
    expect(legacyRawPlaybackIndexToLogicalStep(items, 1)).toBe(0)
  })
})

describe('navigateVnLogicalStep', () => {
  it('advances by one logical step for two text beats', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'a.png' },
      { type: 'text', id: 'a', line: 2, text: 'a', tts_cached: undefined },
      { type: 'image', line: 3, alt: '', url: 'b.png' },
      { type: 'text', id: 'b', line: 4, text: 'b', tts_cached: undefined },
    ]
    expect(navigateVnLogicalStep(items, 0, 1, false)).toBe(1)
    expect(navigateVnLogicalStep(items, 1, -1, false)).toBe(0)
  })

  it('advances from last real item to virtual index when cursorCliSlot', () => {
    const items: PlaybackItem[] = [
      { type: 'text', id: 'a', line: 1, text: 'a', tts_cached: undefined },
    ]
    expect(navigateVnLogicalStep(items, 0, 1, true)).toBe(1)
    expect(navigateVnLogicalStep(items, 0, 1, false)).toBe(0)
  })

  it('stays on virtual index when advancing forward', () => {
    const items: PlaybackItem[] = [
      { type: 'text', id: 'a', line: 1, text: 'a', tts_cached: undefined },
    ]
    expect(navigateVnLogicalStep(items, 1, 1, true)).toBe(1)
  })

  it('returns from virtual index to last real item backward', () => {
    const items: PlaybackItem[] = [
      { type: 'text', id: 'a', line: 1, text: 'a', tts_cached: undefined },
      { type: 'text', id: 'b', line: 2, text: 'b', tts_cached: undefined },
    ]
    expect(navigateVnLogicalStep(items, 2, -1, true)).toBe(1)
  })

  it('from last text after image advances to virtual when slot', () => {
    const items: PlaybackItem[] = [
      { type: 'image', line: 1, alt: '', url: 'x.png' },
      { type: 'text', id: 'b', line: 2, text: 'b', tts_cached: undefined },
    ]
    expect(vnLogicalStepCount(items, true)).toBe(2)
    expect(navigateVnLogicalStep(items, 0, 1, true)).toBe(1)
    expect(navigateVnLogicalStep(items, 1, 1, true)).toBe(1)
  })
})
