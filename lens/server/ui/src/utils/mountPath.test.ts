import { describe, expect, it } from 'vitest'
import { normalizeMountRelativePath } from './mountPath'

describe('normalizeMountRelativePath', () => {
  it('extracts path after mount/file', () => {
    expect(normalizeMountRelativePath('/mount/file/sub/x.png')).toBe('sub/x.png')
    expect(normalizeMountRelativePath('mount/file/foo.jpg')).toBe('foo.jpg')
  })

  it('passes through plain relative keys', () => {
    expect(normalizeMountRelativePath('hero.png')).toBe('hero.png')
  })
})
