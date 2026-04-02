import { attachFile } from '../services/api'
import { treeRefreshTrigger, transactionResult, mediaUploadRequest, mediaRemoveRequest, mediaPreviewRequest } from '../stores/ui'
import type { CommandContext, CommandModule } from './common'
import { normalizeAddress } from './common'

const mediaHandler = async (
  _command: string,
  _payload: string,
  ctx: CommandContext,
): Promise<{ clearInput: boolean }> => {
  transactionResult.set(null)
  const action = ctx.args.positional['action'] as string | undefined
  const path = ctx.args.positional['path'] as string | undefined

  if (!action) return { clearInput: false }

  if (action === 'upload') {
    let dir = path ?? ''
    if (dir) {
      const lastSegment = dir.split('/').pop() ?? ''
      if (lastSegment.includes('.')) {
        const slashIdx = dir.lastIndexOf('/')
        dir = slashIdx >= 0 ? dir.slice(0, slashIdx) : ''
      }
    }
    mediaUploadRequest.set({ dir })
    return { clearInput: false }
  }

  if (action === 'preview') {
    if (!path) return { clearInput: false }
    mediaPreviewRequest.set({ path })
    return { clearInput: false }
  }

  if (!path) return { clearInput: false }

  if (action === 'download') {
    const filename = path.split('/').pop() ?? path
    const a = document.createElement('a')
    a.href = `/mount/file/${path}`
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    return { clearInput: true }
  }

  if (action === 'remove') {
    mediaRemoveRequest.set({ path })
    return { clearInput: false }
  }

  if (action === 'attach') {
    const rawAddress = ctx.args.positional['address'] as string | undefined
    const attachAddress = normalizeAddress(rawAddress)
    const lineRaw = ctx.args.positional['line'] as string | undefined
    const parsedLine = lineRaw !== undefined && lineRaw !== '' ? parseInt(lineRaw, 10) : NaN
    const attachLine = Number.isInteger(parsedLine) ? parsedLine : undefined
    try {
      const result = await attachFile(path, {
        ...(attachAddress !== undefined ? { address: attachAddress } : {}),
        ...(attachLine !== undefined ? { line: attachLine } : {}),
      })
      if (result.status === 'ok') {
        if (ctx.onDone) await ctx.onDone()
        treeRefreshTrigger.update((n) => n + 1)
        return { clearInput: true }
      }
      transactionResult.set({
        title: 'Attach error',
        message: result.detail ?? 'Unknown error',
      })
      return { clearInput: false }
    } catch (err) {
      transactionResult.set({
        title: 'Attach error',
        message: err instanceof Error ? err.message : String(err),
      })
      return { clearInput: false }
    }
  }

  return { clearInput: false }
}

export const mediaModule: CommandModule = {
  commands: (stats) =>
    stats.has_mount
      ? [
          {
            trigger: 'media',
            group: 'narrative',
            hint: 'attach (address, line), upload, download, or remove a media file',
            positional: [
              {
                name: 'action',
                valueType: 'slug',
                required: true,
                slugSource: 'attach,upload,download,preview,remove'
              },
              {
                name: 'path',
                valueType: 'file-path',
                required: false,
                hint: 'mount-relative path',
              },
              {
                name: 'address',
                valueType: 'address',
                required: false,
                hint: 'narrative address (attach)',
              },
              {
                name: 'line',
                valueType: 'line',
                required: false,
                hint: 'line to insert after (attach)',
              },
            ],
          },
        ]
      : [],
  handler: mediaHandler,
}
