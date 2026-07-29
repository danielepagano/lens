import { describe, it, expect } from 'vitest'
import { buildLayeredMountEmbedLine, buildMountEmbedLine } from './mountEmbed'

describe('buildMountEmbedLine', () => {
  it('builds a markdown image embed', () => {
    expect(buildMountEmbedLine('images/hero.jpg')).toBe('![hero.jpg](/mount/file/images/hero.jpg)')
  })

  it('builds a video embed', () => {
    const embed = buildMountEmbedLine('clips/intro.mp4')
    expect(embed).toContain('<video')
    expect(embed).toContain('/mount/file/clips/intro.mp4')
  })
})

describe('buildLayeredMountEmbedLine', () => {
  it('contains both urls and composite classes', () => {
    const embed = buildLayeredMountEmbedLine('bg/scene.jpg', 'fg/amy.png')
    expect(embed).toContain('class="lens-vn-composite"')
    expect(embed).toContain('/mount/file/bg/scene.jpg')
    expect(embed).toContain('/mount/file/fg/amy.png')
    expect(embed).toContain('class="lens-vn-bg"')
    expect(embed).toContain('class="lens-vn-fg"')
  })

  it('is a single line', () => {
    expect(buildLayeredMountEmbedLine('bg/scene.jpg', 'fg/amy.png')).not.toContain('\n')
  })

  it('strips a leading slash from both paths', () => {
    const embed = buildLayeredMountEmbedLine('/bg/scene.jpg', '/fg/amy.png')
    expect(embed).toContain('/mount/file/bg/scene.jpg')
    expect(embed).toContain('/mount/file/fg/amy.png')
  })

  it('escapes quotes in the filename', () => {
    const embed = buildLayeredMountEmbedLine('bg/we"ird.jpg', 'fg/amy.png')
    expect(embed).toContain('&quot;')
    expect(embed).not.toContain('"we"ird.jpg"')
  })
})
