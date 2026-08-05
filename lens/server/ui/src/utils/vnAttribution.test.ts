import { describe, expect, it } from 'vitest'
import type { PlaybackItem } from '../services/api'
import {
  buildLineAttributionByLine,
  isAttributedDialogueLine,
  parseAttributedPlaybackText,
} from './vnAttribution'

const mockQuote = (_label: string) => ({ accent: '10 20% 30%', border: '10 20% 40%' })

describe('buildLineAttributionByLine', () => {
  it('maps line to pill from the attributed chunk; continuations reuse lookup', () => {
    const items = [
      { type: 'text' as const, id: 'a', line: 3, text: '> [GM] First piece', ai_gen: true },
      { type: 'text' as const, id: 'b', line: 3, text: 'second piece', ai_gen: true },
    ] satisfies PlaybackItem[]
    const byLine = buildLineAttributionByLine(items, mockQuote)
    const pill = byLine.get(3)
    expect(pill?.label).toBe('GM')
    const fromFirst = parseAttributedPlaybackText('> [GM] First piece', mockQuote)
    expect(pill?.style).toBe(fromFirst?.style)
  })

  it('omits lines with no attributed chunk', () => {
    const items = [
      { type: 'text' as const, id: 'a', line: 2, text: 'Plain.', ai_gen: false },
    ] satisfies PlaybackItem[]
    const byLine = buildLineAttributionByLine(items, mockQuote)
    expect(byLine.has(2)).toBe(false)
  })
})

describe('isAttributedDialogueLine', () => {
  it('is true for a companion speaker line', () => {
    expect(isAttributedDialogueLine('> [Amy] Hey you.')).toBe(true)
  })

  it('is false for narration prose, even multi-line', () => {
    expect(isAttributedDialogueLine('The afternoon light is low and golden.')).toBe(false)
  })

  it('only inspects the first line of a chunk', () => {
    expect(isAttributedDialogueLine('Plain lead-in.\n> [Amy] trailing')).toBe(false)
  })
})
