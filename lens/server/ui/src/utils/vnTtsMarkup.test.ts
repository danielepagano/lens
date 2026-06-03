import { describe, it, expect } from 'vitest'
import { extractDisplayBody, segmentTtsMarkup } from './vnTtsMarkup'

describe('vnTtsMarkup', () => {
  it('extractDisplayBody strips attributed first line prefix', () => {
    expect(extractDisplayBody('> [Amy] Hello there')).toBe('Hello there')
  })

  it('segmentTtsMarkup applies whisper styling without rendering tags', () => {
    const segs = segmentTtsMarkup('Hello <whisper>world</whisper>!')
    expect(segs.some((s) => s.text === 'world' && s.className.includes('vn-tts-italic'))).toBe(true)
    expect(segs.some((s) => s.text.includes('<whisper>'))).toBe(false)
  })

  it('segmentTtsMarkup omits bracket pause tags', () => {
    const segs = segmentTtsMarkup('Wait [pause] here')
    expect(segs.map((s) => s.text).join('')).toBe('Wait  here')
  })
})
