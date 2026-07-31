import type { MediaCarouselRequest } from '../../stores/ui'
import { mountCacheRefreshTrigger } from '../../stores/ui'
import {
  attachFile,
  deleteMountPath,
  deleteMountPathConfirmed,
  getMountMetadata,
  moveMountFile,
  uploadMountFile,
  getMountFilePath,
  runEdit,
  StreamBusyError,
  type MountEntry,
  type DeleteMountConfirmRequired,
} from '../../services/api'
import { buildLayeredMountEmbedLine, buildMountEmbedLine } from '../../utils/mountEmbed'
import { compositeRole, otherCompositeRole, type CompositeRole } from '../../utils/mediaComposite'
import { runChromakeyPreview, startChromakeySession } from './mediaCompositeHandlers'
import { dirnameOfPath, requiredKeywordsForDir } from './mediaSearchHandlers'

export interface PendingLayer {
  path: string
  role: CompositeRole
}

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
  getPendingDeleteConfirm: () => boolean
  setPendingDeleteConfirm: (value: boolean) => void
  getPendingLayer: () => PendingLayer | null
  setPendingLayer: (value: PendingLayer | null) => void
  openSearchWithQuery: (query: string) => void
  close: () => void
  onDone?: () => void
  loadDir: () => Promise<void>
  navigateTo: (dir: string) => Promise<void>
}

/**
 * Pre-filled search query for finding the complementary composite layer:
 * requires an image tagged with the opposite role, plus the folder the
 * first pick came from as freely editable/removable terms (same convention
 * as `requiredKeywordsForDir`).
 */
function pairingSearchQuery(pickedPath: string, role: CompositeRole): string {
  const base = `image! composite! ${otherCompositeRole(role)}!`
  const dirTerms = requiredKeywordsForDir(dirnameOfPath(pickedPath))
  return dirTerms ? `${base} ${dirTerms}` : `${base} `
}

/**
 * Resolve which of the two picked files is the background and which is the
 * foreground from their own composite metadata, not pick order. Exactly
 * one of the pair must be tagged `foreground` — a background can be any
 * image, tagged or not, since (unlike the foreground's chromakey alpha)
 * the `composite: background` tag is purely a search convenience, not a
 * functional requirement.
 */
async function resolveLayers(
  pending: PendingLayer,
  selectedPath: string,
): Promise<{ bgPath: string; fgPath: string } | { error: string }> {
  const selectedRole = await lookupCompositeRole(selectedPath)
  const pendingIsFg = pending.role === 'foreground'
  const selectedIsFg = selectedRole === 'foreground'

  if (pendingIsFg && selectedIsFg) {
    return { error: 'Both files are tagged foreground — pick a background instead.' }
  }
  if (!pendingIsFg && !selectedIsFg) {
    return {
      error:
        'Neither file is tagged foreground — a composite needs one image tagged composite: foreground.',
    }
  }
  return pendingIsFg
    ? { bgPath: selectedPath, fgPath: pending.path }
    : { bgPath: pending.path, fgPath: selectedPath }
}

async function completeLayeredAttach(
  ctx: MediaCarouselHandlerCtx,
  request: MediaCarouselRequest,
  pending: PendingLayer,
  selectedPath: string,
): Promise<void> {
  const layers = await resolveLayers(pending, selectedPath)
  if ('error' in layers) {
    ctx.setError(layers.error)
    return
  }
  const { bgPath, fgPath } = layers
  try {
    const result = await attachFile(bgPath, {
      fgPath,
      ...(request.attachAddress ? { address: request.attachAddress } : {}),
      ...(request.attachLine !== undefined ? { line: request.attachLine } : {}),
    })
    if (result.status === 'ok') {
      ctx.setPendingLayer(null)
      ctx.close()
      ctx.onDone?.()
      return
    }
    ctx.setError(result.detail ?? 'Attach failed')
  } catch (e) {
    ctx.setError(e instanceof Error ? e.message : String(e))
  }
}

async function completeLayeredReplace(
  ctx: MediaCarouselHandlerCtx,
  addr: string,
  ln: number,
  pending: PendingLayer,
  selectedPath: string,
): Promise<void> {
  const layers = await resolveLayers(pending, selectedPath)
  if ('error' in layers) {
    ctx.setError(layers.error)
    return
  }
  const { bgPath, fgPath } = layers
  try {
    const replacement = buildLayeredMountEmbedLine(bgPath, fgPath)
    const result = await runEdit(
      { address: addr, start_line: ln, end_line: ln, prompt: replacement, replace: true },
      () => {},
    )
    if (result.type === 'error') {
      ctx.setError(result.message)
      return
    }
    ctx.setPendingLayer(null)
    ctx.close()
    ctx.onDone?.()
  } catch (e) {
    if (e instanceof StreamBusyError) {
      ctx.setError(e.message)
      return
    }
    ctx.setError(e instanceof Error ? e.message : String(e))
  }
}

/** Composite role of *path*, or `null` on lookup failure (never blocks a plain attach/replace). */
async function lookupCompositeRole(path: string): Promise<CompositeRole | null> {
  try {
    const meta = await getMountMetadata(path)
    return compositeRole(meta)
  } catch {
    return null
  }
}

export async function attachFromCarousel(ctx: MediaCarouselHandlerCtx): Promise<void> {
  const selectedPath = ctx.getSelectedPath()
  const request = ctx.getRequest()
  if (!selectedPath || !request) return
  ctx.setError(null)

  const pending = ctx.getPendingLayer()
  if (pending && pending.path === selectedPath) {
    ctx.setError('Pick a different file for the other layer.')
    return
  }

  if (request.mode === 'replace') {
    const addr = request.attachAddress
    const ln = request.replaceImageLine
    if (addr === undefined || ln === undefined) return

    if (pending) {
      await completeLayeredReplace(ctx, addr, ln, pending, selectedPath)
      return
    }

    const role = await lookupCompositeRole(selectedPath)
    if (role) {
      ctx.setPendingLayer({ path: selectedPath, role })
      ctx.openSearchWithQuery(pairingSearchQuery(selectedPath, role))
      return
    }

    try {
      const replacement = buildMountEmbedLine(selectedPath)
      const result = await runEdit(
        { address: addr, start_line: ln, end_line: ln, prompt: replacement, replace: true },
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

  if (pending) {
    await completeLayeredAttach(ctx, request, pending, selectedPath)
    return
  }

  // A background/foreground-tagged image pairs with its complementary layer before attaching.
  const role = await lookupCompositeRole(selectedPath)
  if (role) {
    ctx.setPendingLayer({ path: selectedPath, role })
    ctx.openSearchWithQuery(pairingSearchQuery(selectedPath, role))
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

/** Picking an image in 'chromakey' mode starts a preview instead of attaching it. */
export function chromakeyFromCarousel(ctx: MediaCarouselHandlerCtx): void {
  const selectedPath = ctx.getSelectedPath()
  if (!selectedPath) return
  const returnToDir = ctx.getCurrentDir()
  ctx.close()
  startChromakeySession(selectedPath, { returnToDir })
  void runChromakeyPreview({ path: selectedPath })
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

  if (ctx.getPendingDeleteConfirm()) {
    ctx.setPendingDeleteConfirm(false)
    try {
      await deleteMountPathConfirmed(selectedPath)
      ctx.setSelectedIndex(-1)
      mountCacheRefreshTrigger.update((n) => n + 1)
      await ctx.loadDir()
    } catch (e) {
      ctx.setError(e instanceof Error ? e.message : String(e))
    }
    return
  }

  try {
    const result = await deleteMountPath(selectedPath)
    if (result.status === 'confirm_required') {
      const confirmData = result as DeleteMountConfirmRequired
      const refCount = confirmData.refs.reduce((n, r) => n + r.line_numbers.length, 0)
      const fileList = confirmData.refs
        .map((r) => `  ${r.file} (line${r.line_numbers.length > 1 ? 's' : ''} ${r.line_numbers.join(', ')})`)
        .join('\n')
      ctx.setError(
        `${refCount} reference(s) in ${confirmData.refs.length} file(s):\n${fileList}\nClick Delete again to confirm removal.`,
      )
      ctx.setPendingDeleteConfirm(true)
      return
    }
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
