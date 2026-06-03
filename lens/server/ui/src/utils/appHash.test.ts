import { describe, expect, it } from 'vitest'
import { buildAppHash, hashAfterNodeResolved, parseAppHash } from './appHash'

describe('parseAppHash', () => {
  it('parses vn, vn_i, and TTS flags (vn_spk=1)', () => {
    const p = parseAppHash('#myproj/chapter/a?vn=1&vn_i=3&vn_spk=1&vn_aa=1&vn_rdr=1')
    expect(p.project).toBe('myproj')
    expect(p.path).toBe('chapter/a')
    expect(p.vn).toBe(true)
    expect(p.vn_i).toBe(3)
    expect(p.vn_i_explicit).toBe(true)
    expect(p.vnTts).toEqual({
      speak: true,
      autoAdvance: true,
      renderNew: true,
    })
    expect(p.vnTtsFromUrl).toBe(true)
    expect(p.kb).toBe(null)
  })

  it('vn_spk=0 is explicit TTS off', () => {
    const p = parseAppHash('#p/n?vn=1&vn_i=0&vn_spk=0')
    expect(p.vnTts).toEqual({
      speak: false,
      autoAdvance: false,
      renderNew: false,
    })
    expect(p.vnTtsFromUrl).toBe(true)
  })

  it('maps legacy vn_tts=auto to speak + autoAdvance + renderNew', () => {
    const p = parseAppHash('#p/n?vn=1&vn_i=0&vn_tts=auto')
    expect(p.vnTts).toEqual({
      speak: true,
      autoAdvance: true,
      renderNew: true,
    })
    expect(p.vnTtsFromUrl).toBe(true)
  })

  it('maps legacy vn_tts=cached to speak only', () => {
    const p = parseAppHash('#p/n?vn=1&vn_tts=cached')
    expect(p.vnTts).toEqual({
      speak: true,
      autoAdvance: false,
      renderNew: false,
    })
  })

  it('buildAppHash encodes vn TTS flags', () => {
    expect(
      buildAppHash('p', 'n', {
        vn: true,
        vn_i: 2,
        vnTts: { speak: true, autoAdvance: false, renderNew: true },
      })
    ).toBe('p/n?vn=1&vn_i=2&vn_spk=1&vn_rdr=1')
  })

  it('buildAppHash encodes vn_spk=0 when speak off', () => {
    expect(
      buildAppHash('p', 'n', {
        vn: true,
        vn_i: 2,
        vnTts: { speak: false, autoAdvance: false, renderNew: false },
      })
    ).toBe('p/n?vn=1&vn_i=2&vn_spk=0')
  })

  it('buildAppHash drops kb when vn', () => {
    expect(buildAppHash('p', 'n', { vn: true, vn_i: 2, vnTts: { speak: false, autoAdvance: false, renderNew: false } })).toBe(
      'p/n?vn=1&vn_i=2&vn_spk=0'
    )
  })

  it('buildAppHash keeps kb when not vn', () => {
    expect(buildAppHash('p', 'n', { kb: 'x.y' })).toBe('p/n?kb=x.y')
  })

  it('buildAppHash encodes vn_i=0 when vn without vn_i option', () => {
    expect(
      buildAppHash('p', 'n', {
        vn: true,
        vnTts: { speak: false, autoAdvance: false, renderNew: false },
      })
    ).toBe('p/n?vn=1&vn_i=0&vn_spk=0')
  })

  it('hashAfterNodeResolved preserves Scene query on same path', () => {
    const h =
      '#indigo/chat/foo?vn=1&vn_i=3&vn_spk=0'
    expect(hashAfterNodeResolved('indigo', 'chat/foo', null, h)).toBe(
      'indigo/chat/foo?vn=1&vn_i=3&vn_spk=0'
    )
  })

  it('hashAfterNodeResolved drops Scene when path changes', () => {
    const h = '#indigo/chat/foo?vn=1&vn_i=3&vn_spk=0'
    expect(hashAfterNodeResolved('indigo', 'chat/bar', null, h)).toBe('indigo/chat/bar')
  })
})
