import { attachFile } from '../services/api'
import { treeRefreshTrigger, transactionResult } from '../stores/ui'
import type { CommandContext, CommandModule } from './common'

const handler = async (
  _command: string,
  _payload: string,
  ctx: CommandContext,
): Promise<{ clearInput: boolean }> => {
  transactionResult.set(null)
  const path = ctx.args.positional['path'] as string | undefined
  if (!path) return { clearInput: false }
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

export const attachModule: CommandModule = {
  commands: (stats) =>
    stats.has_mount
      ? [
          {
            trigger: 'attach',
            group: 'narrative',
            hint: 'attach a media file at cursor',
            positional: [
              {
                name: 'path',
                valueType: 'file-path',
                required: true,
                hint: 'mount-relative path',
              },
            ],
          },
        ]
      : [],
  handler,
}
