import { describe, it, expect } from 'vitest'
import {
  appendFinalExt,
  finalSegmentExt,
  isMountImagePath,
  mountPathExt,
  stripFinalExt,
} from './mountFileTypes'

describe('mountFileTypes', () => {
  it('reads extension from path', () => {
    expect(mountPathExt('photos/hero.png')).toBe('.png')
    expect(mountPathExt('folder')).toBe('')
  })

  it('detects image paths', () => {
    expect(isMountImagePath('a.jpg')).toBe(true)
    expect(isMountImagePath('a.pdf')).toBe(false)
  })

  it('finalSegmentExt uses basename only', () => {
    expect(finalSegmentExt('dir/old.name.txt')).toBe('.txt')
  })

  it('stripFinalExt and appendFinalExt round-trip', () => {
    expect(stripFinalExt('dir/photo.jpg')).toBe('dir/photo')
    expect(appendFinalExt('dir/photo', '.webp')).toBe('dir/photo.webp')
  })
})
