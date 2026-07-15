import type { MediaCarouselRequest } from '../../stores/ui'
import { mountCacheRefreshTrigger } from '../../stores/ui'
import {
  attachFile,
  deleteMountPath,
  moveMountFile,
  uploadMountFile,
  getMountFilePath,
  runEdit,
  StreamBusyError,
  type MountEntry,
} from '../../services/api'
import { buildMountEmbedLine } from '../../utils/mountEmbed'

export type MediaCarouselHandlerCtx = {
  getRequest: () => MediaCarouselRequest | null
  getSelectedPath: () => string | null
  getCurrentDir: () => string
  getEntries: () => readonly MountEntry[]
  setError: (message: string | null) => void
  setRenaming: (value: boolean) => void
  setSelectedIndex: (index: number) => void
  setRemoving: (value: boolean) => void
  setUploading: (value: boolean) => void
  close: () => void
  onDone?: () => void
  loadDir: () => Promise<void>
  navigateTo: (dir: string) => Promise<void>
}

export async function attachFromCarousel(ctx: MediaCarouselHandlerCtx): Promise<void> {
  const selectedPath = ctx.getSelectedPath()
  const request = ctx.getRequest()
  if (!selectedPath || !request) return
  ctx.setError(null)
  if (request.mode === 'replace') {
    const addr = request.attachAddress
    const ln = request.replaceImageLine
    if (addr === undefined || ln === undefined) return
    try {
      const replacement = buildMountEmbedLine(selectedPath)
      const result = await runEdit(
        {
          address: addr,
          start_line: ln,
          end_line: ln,
          prompt: replacement,
          replace: true,
        },
        () => {},
      )
      if (result.type === 'error') {
        ctx.setError(result.message)
        return
      }
      ctx.close()
      ctx.onDone?.()
    } catch (e) {
      if (e instanceof StreamBusyError) {
        ctx.setError(e.message)
        return
      }
      ctx.setError(e instanceof Error ? e.message : String(e))
    }
    return
  }
  try {
    const result = await attachFile(selectedPath, {
      ...(request.attachAddress ? { address: request.attachAddress } : {}),
      ...(request.attachLine !== undefined ? { line: request.attachLine } : {}),
    })
    if (result.status === 'ok') {
      ctx.close()
      ctx.onDone?.()
      return
    }
    ctx.setError(result.detail ?? 'Attach failed')
  } catch (e) {
    ctx.setError(e instanceof Error ? e.message : String(e))
  }
}

export async function removeFromScene(ctx: MediaCarouselHandlerCtx): Promise<void> {
  const request = ctx.getRequest()
  if (!request || request.mode !== 'replace') return
  const addr = request.attachAddress
  const ln = request.replaceImageLine
  if (addr === undefined || ln === undefined) return
  ctx.setRemoving(true)
  ctx.setError(null)
  try {
    const result = await runEdit(
      {
        address: addr,
        start_line: ln,
        end_line: ln,
        prompt: '',
        replace: true,
      },
      () => {},
    )
    if (result.type === 'error') {
      ctx.setError(result.message)
      return
    }
    ctx.close()
    ctx.onDone?.()
  } catch (e) {
    if (e instanceof StreamBusyError) {
      ctx.setError(e.message)
      return
    }
    ctx.setError(e instanceof Error ? e.message : String(e))
  } finally {
    ctx.setRemoving(false)
  }
}

export function downloadFromCarousel(ctx: MediaCarouselHandlerCtx): void {
  const selectedPath = ctx.getSelectedPath()
  if (!selectedPath) return
  const a = document.createElement('a')
  a.href = getMountFilePath(selectedPath)
  a.download = selectedPath.split('/').pop() ?? selectedPath
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export async function confirmRenameInCarousel(
  ctx: MediaCarouselHandlerCtx,
  newNameRaw: string,
): Promise<void> {
  const selectedPath = ctx.getSelectedPath()
  if (!selectedPath) return
  const newName = newNameRaw.trim()
  if (!newName) {
    ctx.setRenaming(false)
    return
  }
  const currentDir = ctx.getCurrentDir()
  const newPath = newName.includes('/') ? newName : (currentDir ? `${currentDir}/${newName}` : newName)
  ctx.setError(null)
  try {
    const result = await moveMountFile(selectedPath, newPath)
    if (result.status === 'ok') {
      ctx.setRenaming(false)
      mountCacheRefreshTrigger.update((n) => n + 1)
      const newFileName = newPath.split('/').pop() ?? newPath
      const lastSlash = newPath.lastIndexOf('/')
      const newDir = lastSlash >= 0 ? newPath.slice(0, lastSlash) : ''
      const currentDir = ctx.getCurrentDir()
      if (newDir !== currentDir) {
        await ctx.navigateTo(newDir)
      } else {
        await ctx.loadDir()
      }
      const entries = ctx.getEntries()
      const idx = entries.findIndex((en) => en.name === newFileName)
      if (idx >= 0) ctx.setSelectedIndex(idx)
      return
    }
    ctx.setError(result.detail ?? 'Rename failed')
  } catch (e) {
    ctx.setError(e instanceof Error ? e.message : String(e))
  }
  ctx.setRenaming(false)
}

export async function deleteFromCarousel(ctx: MediaCarouselHandlerCtx): Promise<void> {
  const selectedPath = ctx.getSelectedPath()
  if (!selectedPath) return
  ctx.setError(null)
  try {
    await deleteMountPath(selectedPath)
    ctx.setSelectedIndex(-1)
    mountCacheRefreshTrigger.update((n) => n + 1)
    await ctx.loadDir()
  } catch (e) {
    ctx.setError(e instanceof Error ? e.message : String(e))
  }
}

export async function uploadToCarousel(ctx: MediaCarouselHandlerCtx, file: File): Promise<void> {
  ctx.setUploading(true)
  ctx.setError(null)
  const currentDir = ctx.getCurrentDir()
  try {
    const result = await uploadMountFile(currentDir, file)
    if (result.status === 'ok') {
      mountCacheRefreshTrigger.update((n) => n + 1)
      await ctx.loadDir()
      const entries = ctx.getEntries()
      const idx = entries.findIndex((en) => en.name === (result.path ?? '').split('/').pop())
      if (idx >= 0) ctx.setSelectedIndex(idx)
    } else {
      ctx.setError(result.detail ?? 'Upload failed')
    }
  } catch (e) {
    ctx.setError(e instanceof Error ? e.message : String(e))
  } finally {
    ctx.setUploading(false)
  }
}
