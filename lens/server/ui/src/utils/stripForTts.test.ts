import { describe, expect, it } from 'vitest'
import { stripForTts } from './stripForTts'

describe('stripForTts', () => {
  it('drops attributed blockquote label', () => {
    expect(stripForTts('> [GM] The rain falls.')).toBe('The rain falls.')
  })

  it('strips heading markers and emphasis like Python', () => {
    const t = stripForTts('### **Bold** title')
    expect(t).not.toContain('#')
    expect(t).not.toContain('*')
    expect(t).toContain('Bold')
    expect(t).toContain('title')
  })
})
