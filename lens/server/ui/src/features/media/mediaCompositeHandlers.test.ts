import { describe, it, expect, vi, beforeEach } from 'vitest'
import { get } from 'svelte/store'
import { mediaCompositeSession } from '../../stores/ui'

vi.mock('../../services/api', () => ({
  previewChromakey: vi.fn(),
  saveChromakey: vi.fn(),
}))

import { previewChromakey, saveChromakey } from '../../services/api'
import {
  buildChromakeyParams,
  parseNumberInput,
  runChromakeyPreview,
  runChromakeySave,
  startChromakeySession,
} from './mediaCompositeHandlers'

const mockPreviewChromakey = vi.mocked(previewChromakey)
const mockSaveChromakey = vi.mocked(saveChromakey)

beforeEach(() => {
  vi.clearAllMocks()
  mediaCompositeSession.set(null)
})

describe('parseNumberInput', () => {
  it('returns undefined for blank input', () => {
    expect(parseNumberInput('')).toBeUndefined()
    expect(parseNumberInput('   ')).toBeUndefined()
  })

  it('parses a valid number', () => {
    expect(parseNumberInput('30')).toBe(30)
    expect(parseNumberInput(' 12.5 ')).toBe(12.5)
  })

  it('returns undefined for non-numeric input', () => {
    expect(parseNumberInput('nope')).toBeUndefined()
  })
})

describe('buildChromakeyParams', () => {
  it('omits blank/invalid overrides', () => {
    const params = buildChromakeyParams('hero.png', {
      key: '',
      coreTol: '',
      residualThresh: '',
      dilatePx: '',
    })
    expect(params).toEqual({ path: 'hero.png' })
  })

  it('includes trimmed key and parsed numeric overrides', () => {
    const params = buildChromakeyParams('hero.png', {
      key: ' FF00FF ',
      coreTol: '30',
      residualThresh: '12',
      dilatePx: '25',
    })
    expect(params).toEqual({
      path: 'hero.png',
      key: 'FF00FF',
      coreTol: 30,
      residualThresh: 12,
      dilatePx: 25,
    })
  })
})

describe('startChromakeySession', () => {
  it('sets an initial previewing state for the given path', () => {
    startChromakeySession('hero.png')
    const s = get(mediaCompositeSession)
    expect(s).toMatchObject({
      path: 'hero.png',
      status: 'previewing',
      previewSrc: null,
      error: null,
    })
  })
})

describe('runChromakeyPreview', () => {
  it('populates the store with a data URL and resolved stats on success', async () => {
    startChromakeySession('hero.png')
    mockPreviewChromakey.mockResolvedValue({
      png_b64: 'ZmFrZQ==',
      key_hex: '#FF00FF',
      core_tol: 15,
      residual_thresh: 10,
      dilate_px: 20,
      n_corners_used: 4,
    })

    await runChromakeyPreview({ path: 'hero.png' })

    const s = get(mediaCompositeSession)
    expect(s?.status).toBe('ready')
    expect(s?.previewSrc).toBe('data:image/png;base64,ZmFrZQ==')
    expect(s?.keyHex).toBe('#FF00FF')
    expect(s?.coreTol).toBe(15)
    expect(s?.nCornersUsed).toBe(4)
    expect(s?.lastParams).toEqual({ path: 'hero.png' })
  })

  it('sets an error status on failure', async () => {
    startChromakeySession('hero.png')
    mockPreviewChromakey.mockRejectedValue(new Error('file not found in mount: hero.png'))

    await runChromakeyPreview({ path: 'hero.png' })

    const s = get(mediaCompositeSession)
    expect(s?.status).toBe('error')
    expect(s?.error).toBe('file not found in mount: hero.png')
  })
})

describe('runChromakeySave', () => {
  it('does nothing without a prior successful preview', async () => {
    startChromakeySession('hero.png')
    await runChromakeySave()
    expect(mockSaveChromakey).not.toHaveBeenCalled()
  })

  it('saves using the params from the last successful preview', async () => {
    startChromakeySession('hero.png')
    mockPreviewChromakey.mockResolvedValue({
      png_b64: 'ZmFrZQ==',
      key_hex: '#FF00FF',
      core_tol: 15,
      residual_thresh: 10,
      dilate_px: 20,
      n_corners_used: 4,
    })
    await runChromakeyPreview({ path: 'hero.png', coreTol: 30 })

    mockSaveChromakey.mockResolvedValue({
      output_path: 'hero_fg.png',
      key_hex: '#FF00FF',
      core_tol: 30,
      residual_thresh: 10,
      dilate_px: 20,
      n_corners_used: 4,
    })
    await runChromakeySave()

    expect(mockSaveChromakey).toHaveBeenCalledWith({ path: 'hero.png', coreTol: 30 })
    const s = get(mediaCompositeSession)
    expect(s?.status).toBe('saved')
    expect(s?.savedPath).toBe('hero_fg.png')
  })

  it('sets an error status on save failure', async () => {
    startChromakeySession('hero.png')
    mockPreviewChromakey.mockResolvedValue({
      png_b64: 'ZmFrZQ==',
      key_hex: '#FF00FF',
      core_tol: 15,
      residual_thresh: 10,
      dilate_px: 20,
      n_corners_used: 4,
    })
    await runChromakeyPreview({ path: 'hero.png' })

    mockSaveChromakey.mockRejectedValue(new Error('boom'))
    await runChromakeySave()

    const s = get(mediaCompositeSession)
    expect(s?.status).toBe('error')
    expect(s?.error).toBe('boom')
  })
})
