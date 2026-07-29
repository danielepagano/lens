import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { MediaCarouselRequest } from '../../stores/ui'

vi.mock('../../services/api', () => ({
  attachFile: vi.fn(),
  getMountMetadata: vi.fn(),
  deleteMountPath: vi.fn(),
  deleteMountPathConfirmed: vi.fn(),
  moveMountFile: vi.fn(),
  uploadMountFile: vi.fn(),
  getMountFilePath: vi.fn((p: string) => `/mount/file/${p}`),
  runEdit: vi.fn(),
  StreamBusyError: class StreamBusyError extends Error {},
}))

import { attachFile, getMountMetadata, runEdit } from '../../services/api'
import { attachFromCarousel, type MediaCarouselHandlerCtx, type PendingLayer } from './mediaCarouselHandlers'

const mockAttachFile = vi.mocked(attachFile)
const mockGetMountMetadata = vi.mocked(getMountMetadata)
const mockRunEdit = vi.mocked(runEdit)

beforeEach(() => {
  vi.clearAllMocks()
})

function makeCtx(overrides: Partial<MediaCarouselHandlerCtx> = {}): {
  ctx: MediaCarouselHandlerCtx
  state: { error: string | null; pendingLayer: PendingLayer | null; closed: boolean; done: boolean }
} {
  const state = {
    error: null as string | null,
    pendingLayer: null as PendingLayer | null,
    closed: false,
    done: false,
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

  it('enters pairing mode instead of attaching when the file is tagged background', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'bg/scene.jpg', name: 'scene.jpg', extension: '.jpg', type: 'image',
      composite: 'background',
    })

    const { ctx, state } = makeCtx()
    await attachFromCarousel(ctx)

    expect(mockAttachFile).not.toHaveBeenCalled()
    expect(state.pendingLayer).toEqual({ path: 'bg/scene.jpg', role: 'background' })
    expect(state.closed).toBe(false)
  })

  it('enters pairing mode when the file is tagged foreground', async () => {
    mockGetMountMetadata.mockResolvedValue({
      relative_path: 'fg/amy.png', name: 'amy.png', extension: '.png', type: 'image',
      composite: 'foreground',
    })

    const { ctx, state } = makeCtx({ getSelectedPath: () => 'fg/amy.png' })
    await attachFromCarousel(ctx)

    expect(state.pendingLayer).toEqual({ path: 'fg/amy.png', role: 'foreground' })
  })

  it('completes a layered attach with bg as path and fg as fgPath, background picked first', async () => {
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '<div>x</div>' })
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

  it('completes a layered attach with bg as path and fg as fgPath, foreground picked first', async () => {
    mockAttachFile.mockResolvedValue({ status: 'ok', type: 'image', embed: '<div>x</div>' })
    const { ctx } = makeCtx({
      getSelectedPath: () => 'bg/scene.jpg',
      getPendingLayer: () => ({ path: 'fg/amy.png', role: 'foreground' }),
    })

    await attachFromCarousel(ctx)

    expect(mockAttachFile).toHaveBeenCalledWith('bg/scene.jpg', { fgPath: 'fg/amy.png' })
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
  })

  it('completes a layered replace with a composite embed once the pair is picked', async () => {
    mockRunEdit.mockResolvedValue({ type: 'done', operator: 'edit', node: '/ch1', interrupted: false })

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
