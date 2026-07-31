import { describe, it, expect } from 'vitest'
import {
  committedWordCount,
  extraMetadataFields,
  formatMetadataValue,
  dirnameOfPath,
  requiredKeywordsForDir,
} from './mediaSearchHandlers'

describe('committedWordCount', () => {
  it('is 0 for empty input', () => {
    expect(committedWordCount('', 0)).toBe(0)
    expect(committedWordCount('   ', 0)).toBe(0)
  })

  it('does not count the word the cursor is typing at the tail', () => {
    expect(committedWordCount('hello', 5)).toBe(0)
    expect(committedWordCount('hello w', 7)).toBe(1)
  })

  it('counts every word once the cursor moves past it (e.g. after a space)', () => {
    expect(committedWordCount('hello ', 6)).toBe(1)
    expect(committedWordCount('hello world ', 12)).toBe(2)
  })

  it('treats cursorPos -1 as "nothing in progress" — every word committed', () => {
    expect(committedWordCount('hello world', -1)).toBe(2)
  })

  it('still excludes the tail word with the cursor even without trailing whitespace', () => {
    expect(committedWordCount('hello world', 11)).toBe(1)
  })

  it('counts an already-finished later word even while editing an earlier one', () => {
    // "hello world" with the cursor inside "hello" (editing a typo there) —
    // "world" already finished and must stay committed regardless.
    expect(committedWordCount('helloo world', 3)).toBe(1)
  })

  it('counts every word when the cursor sits between them, touching neither', () => {
    expect(committedWordCount('hello  world', 6)).toBe(2)
  })

  it('ignores leading whitespace', () => {
    expect(committedWordCount('   hello world ', 16)).toBe(2)
  })

  it('collapses runs of whitespace', () => {
    expect(committedWordCount('hello   world  ', 16)).toBe(2)
  })
})

describe('extraMetadataFields', () => {
  it('excludes reserved path-derived keys and score', () => {
    const item = {
      relative_path: 'amy/house.jpg',
      name: 'house.jpg',
      extension: '.jpg',
      type: 'image',
      _score: 4.5,
      prompt: 'a quick brown fox',
      composite: { type: 'subject' },
    }
    expect(extraMetadataFields(item)).toEqual([
      ['prompt', 'a quick brown fox'],
      ['composite', { type: 'subject' }],
    ])
  })

  it('returns empty for a bare path with no sidecar data', () => {
    const item = { relative_path: 'a.jpg', name: 'a.jpg', extension: '.jpg', type: 'image', _score: 1 }
    expect(extraMetadataFields(item)).toEqual([])
  })
})

describe('formatMetadataValue', () => {
  it('stringifies primitives', () => {
    expect(formatMetadataValue('brown')).toBe('brown')
    expect(formatMetadataValue(42)).toBe('42')
    expect(formatMetadataValue(true)).toBe('true')
  })

  it('joins arrays with commas', () => {
    expect(formatMetadataValue(['a', 'b', 'c'])).toBe('a, b, c')
  })

  it('flattens nested objects as key: value pairs', () => {
    expect(formatMetadataValue({ type: 'subject', role: 'fg' })).toBe('type: subject, role: fg')
  })

  it('treats null/undefined as empty', () => {
    expect(formatMetadataValue(null)).toBe('')
    expect(formatMetadataValue(undefined)).toBe('')
  })
})

describe('dirnameOfPath', () => {
  it('returns the directory portion of a nested path', () => {
    expect(dirnameOfPath('amy/house/office.jpg')).toBe('amy/house')
  })

  it('returns empty for a root-level path', () => {
    expect(dirnameOfPath('office.jpg')).toBe('')
  })
})

describe('requiredKeywordsForDir', () => {
  it('returns empty for the root folder', () => {
    expect(requiredKeywordsForDir('')).toBe('')
  })

  it('turns a single segment into one required term with a trailing space', () => {
    expect(requiredKeywordsForDir('amy')).toBe('amy! ')
  })

  it('turns each path segment into a required term, in order', () => {
    expect(requiredKeywordsForDir('amy/house')).toBe('amy! house! ')
  })

  it('ignores stray slashes', () => {
    expect(requiredKeywordsForDir('/amy/house/')).toBe('amy! house! ')
  })
})
