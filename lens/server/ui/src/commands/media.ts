import { attachFile } from '../services/api'
import { treeRefreshTrigger, transactionResult, mediaUploadRequest, mediaRemoveRequest } from '../stores/ui'
import type { CommandContext, CommandModule } from './common'

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
    try {
      const result = await attachFile(path)
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
            hint: 'attach, upload, download, or remove a media file',
            positional: [
              {
                name: 'action',
                valueType: 'slug',
                required: true,
                slugSource: 'attach, upload,download,remove'
              },
              {
                name: 'path',
                valueType: 'file-path',
                required: false,
                hint: 'mount-relative path',
              },
            ],
          },
        ]
      : [],
  handler: mediaHandler,
}
