import { describe, it, expect, vi, beforeEach } from 'vitest'
import { get } from 'svelte/store'
import type { MediaCarouselRequest } from '../../stores/ui'
import { mediaCompositeSession } from '../../stores/ui'

vi.mock('../../services/api', () => ({
  attachFile: vi.fn(),
  getMountMetadata: vi.fn(),
  deleteMountPath: vi.fn(),
  deleteMountPathConfirmed: vi.fn(),
  moveMountFile: vi.fn(),
  narrativePin: vi.fn(),
  uploadMountFile: vi.fn(),
  getMountFilePath: vi.fn((p: string) => `/mount/file/${p}`),
  runEdit: vi.fn(),
  previewChromakey: vi.fn(),
  saveChromakey: vi.fn(),
  StreamBusyError: class StreamBusyError extends Error {},
}))

import { attachFile, getMountMetadata, narrativePin, previewChromakey, runEdit } from '../../services/api'
import {
  attachFromCarousel,
  chromakeyFromCarousel,
  confirmAnchorFromCarousel,
  type MediaCarouselHandlerCtx,
  type PendingLayer,
} from './mediaCarouselHandlers'

const mockAttachFile = vi.mocked(attachFile)
const mockGetMountMetadata = vi.mocked(getMountMetadata)
const mockRunEdit = vi.mocked(runEdit)
const mockPreviewChromakey = vi.mocked(previewChromakey)
const mockNarrativePin = vi.mocked(narrativePin)

beforeEach(() => {
  vi.clearAllMocks()
  mediaCompositeSession.set(null)
})

function makeCtx(overrides: Partial<MediaCarouselHandlerCtx> = {}): {
  ctx: MediaCarouselHandlerCtx
  state: {
    error: string | null
    pendingLayer: PendingLayer | null
    closed: boolean
    done: boolean
    searchQuery: string | null
  }
} {
  const state = {
    error: null as string | null,
    pendingLayer: null as PendingLayer | null,
    closed: false,
    done: false,
    searchQuery: null as string | null,
  }
  const ctx: MediaCarouselHandlerCtx = {
    getRequest: () => ({ mode: 'attach', dir: '' }) as MediaCarouselRequest,
    getSelectedPath: () => 'bg/scene.jpg',
    getCurrentDir: () => '',
    getEntries: () => [],
    setError: (m) => {
      state.error = m
    },
    setRenaming: () => {},
    setSelectedIndex: () => {},
    setRemoving: () => {},
    setUploading: () => {},
    getPendingDeleteConfirm: () => false,
    setPendingDeleteConfirm: () => {},
    getPendingLayer: () => state.pendingLayer,
    setPendingLayer: (v) => {
      state.pendingLayer = v
    },
    openSearchWithQuery: (q) => {
      state.searchQuery = q
    },
    close: () => {
      state.closed = true
    },
    onDone: () => {
      state.done = true
    },
    loadDir: async () => {},
    navigateTo: async () => {},
    ...overrides,
  }
  return { ctx, state }
}

describe('attachFromCarousel — composite pairing', () => {
  it('attaches plainly when the selected file has no composite role', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
    })
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '![x](y)' })

    const { ctx, state } = makeCtx()
    await attachFromCarousel(ctx)

    expect(mockAttachFile).toHaveBeenCalledWith('bg/scene.jpg', {})
    expect(state.closed).toBe(true)
    expect(state.done).toBe(true)
    expect(state.pendingLayer).toBeNull()
  })

  it('enters pairing mode instead of attaching when the file is tagged background, and pre-fills a search for a foreground in the same folder', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
      composite: 'background',
    })

    const { ctx, state } = makeCtx()
    await attachFromCarousel(ctx)

    expect(mockAttachFile).not.toHaveBeenCalled()
    expect(state.pendingLayer).toEqual({ path: 'bg/scene.jpg', role: 'background' })
    expect(state.closed).toBe(false)
    expect(state.searchQuery).toBe('image! composite! foreground! bg! ')
  })

  it('enters pairing mode when the file is tagged foreground, and pre-fills a search for a background', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'fg/amy.png', name: 'amy.png', extension: '.png', type: 'image',
      composite: 'foreground',
    })

    const { ctx, state } = makeCtx({ getSelectedPath: () => 'fg/amy.png' })
    await attachFromCarousel(ctx)

    expect(state.pendingLayer).toEqual({ path: 'fg/amy.png', role: 'foreground' })
    expect(state.searchQuery).toBe('image! composite! background! fg! ')
  })

  it('completes a layered attach with bg as path and fg as fgPath, background picked first', async () => {
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '<div>x</div>' })
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'fg/amy.png', name: 'amy.png', extension: '.png', type: 'image',
      composite: 'foreground',
    })
    const { ctx, state } = makeCtx({
      getSelectedPath: () => 'fg/amy.png',
      getPendingLayer: () => ({ path: 'bg/scene.jpg', role: 'background' }),
    })

    await attachFromCarousel(ctx)

    expect(mockAttachFile).toHaveBeenCalledWith('bg/scene.jpg', { fgPath: 'fg/amy.png' })
    expect(state.pendingLayer).toBeNull()
    expect(state.closed).toBe(true)
    expect(state.done).toBe(true)
  })

  it('completes a layered attach with bg as path and fg as fgPath, foreground picked first, and an untagged file is accepted as background', async () => {
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '<div>x</div>' })
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
    })
    const { ctx } = makeCtx({
      getSelectedPath: () => 'bg/scene.jpg',
      getPendingLayer: () => ({ path: 'fg/amy.png', role: 'foreground' }),
    })

    await attachFromCarousel(ctx)

    expect(mockAttachFile).toHaveBeenCalledWith('bg/scene.jpg', { fgPath: 'fg/amy.png' })
  })

  it('rejects completing the pair when both files are tagged foreground', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'fg2/other.png', name: 'other.png', extension: '.png', type: 'image',
      composite: 'foreground',
    })
    const { ctx, state } = makeCtx({ getSelectedPath: () => 'fg2/other.png' })
    ctx.setPendingLayer({ path: 'fg/amy.png', role: 'foreground' })

    await attachFromCarousel(ctx)

    expect(mockAttachFile).not.toHaveBeenCalled()
    expect(state.error).toMatch(/both.*foreground/i)
    expect(state.pendingLayer).toEqual({ path: 'fg/amy.png', role: 'foreground' })
  })

  it('rejects completing the pair when neither file is tagged foreground', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg2/other.jpg', name: 'other.jpg', extension: '.jpg', type: 'image',
    })
    const { ctx, state } = makeCtx({ getSelectedPath: () => 'bg2/other.jpg' })
    ctx.setPendingLayer({ path: 'bg/scene.jpg', role: 'background' })

    await attachFromCarousel(ctx)

    expect(mockAttachFile).not.toHaveBeenCalled()
    expect(state.error).toMatch(/neither.*foreground/i)
    expect(state.pendingLayer).toEqual({ path: 'bg/scene.jpg', role: 'background' })
  })

  it('rejects picking the same file for both layers', async () => {
    const { ctx, state } = makeCtx({
      getSelectedPath: () => 'bg/scene.jpg',
      getPendingLayer: () => ({ path: 'bg/scene.jpg', role: 'background' }),
    })

    await attachFromCarousel(ctx)

    expect(mockAttachFile).not.toHaveBeenCalled()
    expect(state.error).toMatch(/different file/)
  })

  it('surfaces an error status from the layered attach without closing', async () => {
    mockAttachFile.mockResolvedValue({ status: 'error', detail: 'boom' })
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'fg/amy.png', name: 'amy.png', extension: '.png', type: 'image',
      composite: 'foreground',
    })
    const { ctx, state } = makeCtx({
      getSelectedPath: () => 'fg/amy.png',
      getPendingLayer: () => ({ path: 'bg/scene.jpg', role: 'background' }),
    })

    await attachFromCarousel(ctx)

    expect(state.error).toBe('boom')
    expect(state.closed).toBe(false)
  })

  it('falls back to a plain attach when the metadata lookup fails', async () => {
    mockGetMountMetadata.mockRejectedValue(new Error('network error'))
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '![x](y)' })

    const { ctx, state } = makeCtx()
    await attachFromCarousel(ctx)

    expect(mockAttachFile).toHaveBeenCalledWith('bg/scene.jpg', {})
    expect(state.closed).toBe(true)
  })

  it('passes address/line through on the plain-attach path', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
    })
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '![x](y)' })

    const { ctx } = makeCtx({
      getRequest: () => ({ mode: 'attach', dir: '', attachAddress: '/ch1', attachLine: 4 }),
    })
    await attachFromCarousel(ctx)

    expect(mockAttachFile).toHaveBeenCalledWith('bg/scene.jpg', { address: '/ch1', line: 4 })
  })
})

describe('attachFromCarousel — replace mode composite pairing', () => {
  const replaceRequest: MediaCarouselRequest = {
    mode: 'replace',
    dir: '',
    attachAddress: '/ch1',
    replaceImageLine: 5,
  }

  it('replaces plainly when the selected file has no composite role', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
    })
    mockRunEdit.mockResolvedValue({ type: 'done', operator: 'edit', node: '/ch1', interrupted: false })

    const { ctx, state } = makeCtx({ getRequest: () => replaceRequest })
    await attachFromCarousel(ctx)

    expect(mockRunEdit).toHaveBeenCalledWith(
      expect.objectContaining({ address: '/ch1', start_line: 5, end_line: 5, replace: true }),
      expect.any(Function),
    )
    expect(state.closed).toBe(true)
  })

  it('enters pairing mode instead of replacing when the file is composite-tagged', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
      composite: 'background',
    })

    const { ctx, state } = makeCtx({ getRequest: () => replaceRequest })
    await attachFromCarousel(ctx)

    expect(mockRunEdit).not.toHaveBeenCalled()
    expect(state.pendingLayer).toEqual({ path: 'bg/scene.jpg', role: 'background' })
    expect(state.closed).toBe(false)
    expect(state.searchQuery).toBe('image! composite! foreground! bg! ')
  })

  it('completes a layered replace with a composite embed once the pair is picked', async () => {
    mockRunEdit.mockResolvedValue({ type: 'done', operator: 'edit', node: '/ch1', interrupted: false })
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'fg/amy.png', name: 'amy.png', extension: '.png', type: 'image',
      composite: 'foreground',
    })

    const { ctx, state } = makeCtx({
      getRequest: () => replaceRequest,
      getSelectedPath: () => 'fg/amy.png',
      getPendingLayer: () => ({ path: 'bg/scene.jpg', role: 'background' }),
    })
    await attachFromCarousel(ctx)

    const call = mockRunEdit.mock.calls[0]?.[0]
    expect(call).toMatchObject({ address: '/ch1', start_line: 5, end_line: 5, replace: true })
    expect(call?.prompt).toContain('lens-vn-composite')
    expect(call?.prompt).toContain('bg/scene.jpg')
    expect(call?.prompt).toContain('fg/amy.png')
    expect(state.pendingLayer).toBeNull()
    expect(state.closed).toBe(true)
  })
})

describe('chromakeyFromCarousel', () => {
  it('does nothing without a selected file', () => {
    const { ctx, state } = makeCtx({ getSelectedPath: () => null })
    chromakeyFromCarousel(ctx)
    expect(state.closed).toBe(false)
    expect(mockPreviewChromakey).not.toHaveBeenCalled()
  })

  it('closes the carousel and starts a chromakey session at the selected file, remembering the dir', () => {
    const { ctx, state } = makeCtx({
      getSelectedPath: () => 'chars/hero.png',
      getCurrentDir: () => 'chars',
    })
    mockPreviewChromakey.mockResolvedValue({
      png_b64: 'ZmFrZQ==',
      n_frames: 1,
      preview_skipped: false,
      key_hex: '#FF00FF',
      core_tol: 15,
      residual_thresh: 10,
      dilate_px: 20,
      n_corners_used: 4,
    })

    chromakeyFromCarousel(ctx)

    expect(state.closed).toBe(true)
    const s = get(mediaCompositeSession)
    expect(s).toMatchObject({ path: 'chars/hero.png', returnToDir: 'chars' })
    expect(mockPreviewChromakey).toHaveBeenCalledWith({ path: 'chars/hero.png' })
  })
})

describe('confirmAnchorFromCarousel', () => {
  it('persists the raw query verbatim to the media_attach anchor on /@cursor', async () => {
    mockNarrativePin.mockResolvedValue({ status: 'ok' })
    const { ctx, state } = makeCtx({ getRequest: () => ({ mode: 'anchor', dir: '' }) })

    await confirmAnchorFromCarousel(ctx, '  image! foreground! amy!  ')

    expect(mockNarrativePin).toHaveBeenCalledWith({
      kind: 'modality',
      operation: 'set',
      modality_id: 'media_attach',
      key: 'anchor',
      value: 'image! foreground! amy!',
      node: '/@cursor',
    })
    expect(state.closed).toBe(true)
    expect(state.done).toBe(true)
  })

  it('confirms facets! when the query is blank, instead of unsetting the anchor', async () => {
    mockNarrativePin.mockResolvedValue({ status: 'ok' })
    const { ctx, state } = makeCtx({ getRequest: () => ({ mode: 'anchor', dir: '' }) })

    await confirmAnchorFromCarousel(ctx, '   ')

    expect(mockNarrativePin).toHaveBeenCalledWith({
      kind: 'modality',
      operation: 'set',
      modality_id: 'media_attach',
      key: 'anchor',
      value: 'facets!',
      node: '/@cursor',
    })
    expect(state.closed).toBe(true)
  })

  it('surfaces a backend error instead of closing', async () => {
    mockNarrativePin.mockResolvedValue({ status: 'error', detail: 'anchor rejected' })
    const { ctx, state } = makeCtx({ getRequest: () => ({ mode: 'anchor', dir: '' }) })

    await confirmAnchorFromCarousel(ctx, 'amy!')

    expect(state.error).toBe('anchor rejected')
    expect(state.closed).toBe(false)
  })

  it('does nothing outside anchor mode', async () => {
    const { ctx } = makeCtx({ getRequest: () => ({ mode: 'attach', dir: '' }) })

    await confirmAnchorFromCarousel(ctx, 'amy!')

    expect(mockNarrativePin).not.toHaveBeenCalled()
  })
})
