import { mediaCarouselRequest, transactionResult } from '../stores/ui'
import type { CommandContext, CommandModule } from './common'
import { normalizeAddress } from './common'

const mediaHandler = async (
  command: string,
  _payload: string,
  ctx: CommandContext,
): Promise<{ clearInput: boolean }> => {
  transactionResult.set(null)

  if (command === 'media-attach') {
    const rawPath = ctx.args.positional['dir'] as string | undefined
    let dir = rawPath ?? ''
    if (dir) {
      const lastSegment = dir.split('/').pop() ?? ''
      if (lastSegment.includes('.')) {
        const slashIdx = dir.lastIndexOf('/')
        dir = slashIdx >= 0 ? dir.slice(0, slashIdx) : ''
      }
    }
    const rawAddress = ctx.args.positional['address'] as string | undefined
    const attachAddress = normalizeAddress(rawAddress)
    const lineRaw = ctx.args.positional['line'] as string | undefined
    const parsedLine = lineRaw !== undefined && lineRaw !== '' ? parseInt(lineRaw, 10) : NaN
    const attachLine = Number.isInteger(parsedLine) ? parsedLine : undefined
    mediaCarouselRequest.set({
      mode: 'attach',
      dir,
      ...(attachAddress !== undefined ? { attachAddress } : {}),
      ...(attachLine !== undefined ? { attachLine } : {}),
    })
    return { clearInput: false }
  }

  if (command === 'media-manage') {
    const rawPath = ctx.args.positional['dir'] as string | undefined
    let dir = rawPath ?? ''
    if (dir) {
      const lastSegment = dir.split('/').pop() ?? ''
      if (lastSegment.includes('.')) {
        const slashIdx = dir.lastIndexOf('/')
        dir = slashIdx >= 0 ? dir.slice(0, slashIdx) : ''
      }
    }
    mediaCarouselRequest.set({ mode: 'manage', dir })
    return { clearInput: false }
  }

  return { clearInput: false }
}

export const mediaModule: CommandModule = {
  commands: (stats) =>
    stats.has_mount
      ? [
          {
            trigger: 'media-attach',
            group: 'narrative',
            cursorTargeting: 'can-override',
            hint: 'browse and attach a media file',
            positional: [
              {
                name: 'dir',
                valueType: 'file-path',
                required: false,
                hint: 'starting folder',
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
          {
            trigger: 'media-manage',
            group: 'narrative',
            cursorTargeting: 'never',
            hint: 'browse and manage media files',
            positional: [
              {
                name: 'dir',
                valueType: 'file-path',
                required: false,
                hint: 'starting folder',
              },
            ],
          },
        ]
      : [],
  handler: mediaHandler,
}
