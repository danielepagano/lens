import {
  cliOutput,
  mediaCarouselRequest,
  mediaPreviewSession,
  transactionResult,
} from '../stores/ui'
import {
  attachFile,
  runMediaGenerate,
  StreamBusyError,
  type MediaGenerateEvent,
  type MediaStartEvent,
} from '../services/api'
import type { ImageBackendStats, Stats } from '../services/api'
import type { CliPayload, CommandContext, CommandDefinition, CommandModule } from './common'
import { normalizeAddress, normalizePromptNodeSliceMentions } from './common'
import {
  buildChromakeyParams,
  runChromakeyPreview,
  runChromakeySave,
  startChromakeySession,
} from '../features/media/mediaCompositeHandlers'

/** Mirrors `lens.core.commands.attach.SUPPORTED_EXTENSIONS` — attachable mount file suffixes. */
const ATTACH_MOUNT_EXTENSIONS = new Set([
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.gif',
  '.mp4',
  '.webm',
  '.mov',
  '.avi',
  '.pdf',
  '.txt',
  '.md',
])

/** Mirrors `lens.core.commands.attach.IMAGE_EXTS` — chromakey only accepts images. */
const CHROMAKEY_IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])

function mountPathFileExtension(path: string): string {
  const seg = path.split('/').pop() ?? path
  const dot = seg.lastIndexOf('.')
  return dot >= 0 ? seg.slice(dot).toLowerCase() : ''
}

const mediaHandler = async (
  command: string,
  _payload: string,
  ctx: CommandContext,
): Promise<{ clearInput: boolean }> => {
  transactionResult.set(null)

  if (command === 'media-attach') {
    const rawPath = ((ctx.args.positional['dir'] as string | undefined) ?? '').trim()
    const rawAddress = ctx.args.positional['address'] as string | undefined
    const attachAddress = normalizeAddress(rawAddress)
    const lineRaw = ctx.args.positional['line'] as string | undefined
    const parsedLine = lineRaw !== undefined && lineRaw !== '' ? parseInt(lineRaw, 10) : NaN
    const attachLine = Number.isInteger(parsedLine) ? parsedLine : undefined
    const attachParams = {
      ...(attachAddress !== undefined ? { address: attachAddress } : {}),
      ...(attachLine !== undefined ? { line: attachLine } : {}),
    }
    const ext = rawPath ? mountPathFileExtension(rawPath) : ''
    if (rawPath && ATTACH_MOUNT_EXTENSIONS.has(ext)) {
      try {
        const result = await attachFile(rawPath, attachParams)
        if (result.status === 'ok') {
          if (ctx.onDone) await ctx.onDone()
          return { clearInput: true }
        }
        cliOutput.set({
          output: result.detail ?? 'Attach failed',
          exitCode: 1,
          streaming: false,
        })
        return { clearInput: false }
      } catch (e) {
        cliOutput.set({
          output: e instanceof Error ? e.message : String(e),
          exitCode: 1,
          streaming: false,
        })
        return { clearInput: false }
      }
    }
    let dir = rawPath
    if (dir) {
      const lastSegment = dir.split('/').pop() ?? ''
      if (lastSegment.includes('.')) {
        const slashIdx = dir.lastIndexOf('/')
        dir = slashIdx >= 0 ? dir.slice(0, slashIdx) : ''
      }
    }
    mediaCarouselRequest.set({
      mode: 'attach',
      dir,
      ...(attachAddress !== undefined ? { attachAddress } : {}),
      ...(attachLine !== undefined ? { attachLine } : {}),
    })
    return { clearInput: true }
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
    return { clearInput: true }
  }

  if (command === 'media-composite') {
    const action = ctx.args.positional['action'] as string | undefined
    if (action !== 'chromakey') {
      cliOutput.set({
        output: 'media-composite: expected action "chromakey"',
        exitCode: 1,
        streaming: false,
      })
      return { clearInput: false }
    }
    const rawPath = ((ctx.args.positional['path'] as string | undefined) ?? '').trim()
    const ext = rawPath ? mountPathFileExtension(rawPath) : ''
    if (rawPath && CHROMAKEY_IMAGE_EXTENSIONS.has(ext)) {
      const key = (ctx.args.options['key'] as string | undefined) ?? ''
      const coreTol = (ctx.args.options['core-tol'] as string | undefined) ?? ''
      const residualThresh = (ctx.args.options['residual-thresh'] as string | undefined) ?? ''
      const dilatePx = (ctx.args.options['dilate-px'] as string | undefined) ?? ''
      startChromakeySession(rawPath)
      const skipped = await runChromakeyPreview(
        buildChromakeyParams(rawPath, { key, coreTol, residualThresh, dilatePx })
      )
      // Invoked with an explicit path and nothing to preview (animated source):
      // the user already said what they want, so don't park on a Save button.
      if (skipped) await runChromakeySave()
      return { clearInput: true }
    }
    let dir = rawPath
    if (dir) {
      const lastSegment = dir.split('/').pop() ?? ''
      if (lastSegment.includes('.')) {
        const slashIdx = dir.lastIndexOf('/')
        dir = slashIdx >= 0 ? dir.slice(0, slashIdx) : ''
      }
    }
    mediaCarouselRequest.set({ mode: 'chromakey', dir })
    return { clearInput: true }
  }

  if (command === 'media-generate') {
    const prompt =
      normalizePromptNodeSliceMentions(
        (ctx.args.positional['prompt'] as string | undefined) || undefined
      )?.trim() ?? ''
    const fromOpt = ctx.args.options['from']
    const from =
      (typeof fromOpt === 'string' ? fromOpt : fromOpt != null ? String(fromOpt) : '')
        .trim() || undefined
    if (!prompt && !from) {
      cliOutput.set({
        output: 'media-generate requires a prompt, or --from with a batch sidecar path',
        exitCode: 1,
        streaming: false,
      })
      return { clearInput: false }
    }
    const model = (ctx.args.options['model'] as string | undefined) || undefined
    const aspect = (ctx.args.options['aspect'] as string | undefined) || undefined
    const size = (ctx.args.options['size'] as string | undefined) || undefined
    const rawBatch = ctx.args.options['batch'] as string | undefined
    const batch =
      rawBatch !== undefined && rawBatch !== '' ? parseInt(String(rawBatch), 10) : undefined
    if (rawBatch !== undefined && rawBatch !== '' && (!Number.isInteger(batch) || (batch as number) < 1)) {
      cliOutput.set({ output: 'media-generate: batch must be a positive integer', exitCode: 1, streaming: false })
      return { clearInput: false }
    }
    const slug = (ctx.args.options['slug'] as string | undefined) || undefined
    const negative = (ctx.args.options['negative'] as string | undefined) || undefined
    const refOpt = ctx.args.options['ref']
    const refs = Array.isArray(refOpt)
      ? refOpt.map((x) => String(x).trim()).filter(Boolean)
      : refOpt != null && refOpt !== ''
        ? [String(refOpt).trim()].filter(Boolean)
        : []
    const rawParams = {
      ...(prompt ? { prompt } : {}),
      ...(from ? { from } : {}),
      ...(model ? { model } : {}),
      ...(aspect ? { aspect } : {}),
      ...(size ? { size } : {}),
      ...(batch !== undefined && Number.isInteger(batch) ? { batch: batch as number } : {}),
      ...(slug ? { slug } : {}),
      ...(negative ? { negative } : {}),
      ...(refs.length ? { refs } : {}),
    }
    mediaPreviewSession.set({
      start: null,
      items: [],
      batchSeq: null,
      status: 'streaming',
      selectedIndex: -1,
      rawParams,
      generationStartedAt: Date.now(),
    })
    const updateSession = (
      fn: (s: import('../stores/ui').MediaPreviewState) => import('../stores/ui').MediaPreviewState
    ) => {
      mediaPreviewSession.update((prev) => (prev ? fn(prev) : prev!))
    }
    try {
      const last = await runMediaGenerate(rawParams, (event: MediaGenerateEvent) => {
        if (event.type === 'start') {
          const s = event as MediaStartEvent
          updateSession((p) => ({ ...p, start: s }))
        } else if (event.type === 'item') {
          const extl = event.ext.toLowerCase()
          const mime =
            extl === 'jpg' || extl === 'jpeg'
              ? 'image/jpeg'
              : extl === 'png'
                ? 'image/png'
                : extl === 'gif'
                  ? 'image/gif'
                  : extl === 'webp'
                    ? 'image/webp'
                    : 'image/png'
          const src = `data:${mime};base64,${event.b64}`
          updateSession((p) => {
            const it = p.items.find((x) => x.index === event.index)
            if (it) {
              it.b64 = event.b64
              it.ext = event.ext
              it.src = src
              return { ...p, items: [...p.items] }
            }
            return {
              ...p,
              items: [
                ...p.items,
                {
                  index: event.index,
                  ext: event.ext,
                  b64: event.b64,
                  src,
                  saved: false,
                  saving: false,
                },
              ],
            }
          })
        } else if (event.type === 'progress') {
          const msg = event.message ?? (event.phase ? `Image: ${event.phase}…` : 'Generating…')
          ctx.setBusyMessage(msg)
        } else if (event.type === 'error') {
          updateSession((p) => ({ ...p, status: 'error', error: event.message }))
          ctx.setBusyMessage(null)
          cliOutput.set({ output: event.message, exitCode: 1, streaming: false })
        } else if (event.type === 'done') {
          updateSession((p) => ({ ...p, status: 'done' }))
        }
      })
      if (last.type === 'error') {
        const msg = last.message
        if (msg && msg !== 'Stream ended without done event') {
          updateSession((p) => (p && p.status !== 'error' ? { ...p, status: 'error', error: msg } : p))
        }
        ctx.setBusyMessage(null)
        if (msg === 'Stream ended without done event') {
          const empty = (() => {
            let emptyPreview = true
            mediaPreviewSession.update((p) => {
              emptyPreview = p !== null && p.items.length === 0
              return p
            })
            return emptyPreview
          })()
          if (empty) {
            mediaPreviewSession.set(null)
            cliOutput.set({ output: 'image generation failed', exitCode: 1, streaming: false })
            return { clearInput: false }
          }
        }
        return { clearInput: false }
      }
    } catch (e) {
      if (e instanceof StreamBusyError) {
        mediaPreviewSession.set(null)
        cliOutput.set({ output: e.message, exitCode: 1, streaming: false })
        return { clearInput: false }
      }
      const m = e instanceof Error ? e.message : String(e)
      mediaPreviewSession.set(null)
      cliOutput.set({ output: m, exitCode: 1, streaming: false })
      return { clearInput: false }
    }
    ctx.setBusyMessage(null)
    return { clearInput: true }
  }

  return { clearInput: false }
}

function optionsWithImageIfMultiple(
  options: CliPayload[],
  stats: Stats
): CliPayload[] {
  const many = (stats.image_backends?.length ?? 0) > 1
  if (many) return options
  return options.filter((o) => o.name !== 'model')
}

function defaultImageBackend(stats: Stats): ImageBackendStats | null {
  const b = stats.image_backends
  return b?.[0] ?? null
}

function mediaGenerateCommandHint(stats: Stats): string {
  const fb = defaultImageBackend(stats)
  if (!fb) {
    return 'Generate images'
  }
  const parts: string[] = [
    `model ${fb.id}`,
    `aspect ${fb.default_aspect}`,
    `size ${fb.default_size}`,
    `batch ${fb.default_batch}`,
    `max ${fb.max_batch}`,
  ]
  return `Generate images — defaults: ${parts.join(', ')}`
}

function d(v: string | null | undefined, fallback: string): string {
  return v != null && v !== '' ? v : fallback
}

function mediaGenerateOptions(stats: Stats): CliPayload[] {
  const fb = defaultImageBackend(stats)
  const maxB = fb?.max_batch
  const batchHint =
    maxB != null ? `default ${fb?.default_batch ?? 1}, max ${maxB}` : `default ${fb?.default_batch ?? 1}`
  return optionsWithImageIfMultiple(
    [
      {
        name: 'model',
        valueType: 'slug',
        slugSource: '[media.image_model]',
        hint: `default ${d(fb?.id, '—')}`,
      },
      {
        name: 'aspect',
        valueType: 'slug',
        slugSource: '[media.image_aspect]',
        hint: `default ${d(fb?.default_aspect, '—')}`,
      },
      {
        name: 'size',
        valueType: 'slug',
        slugSource: '[media.image_size]',
        hint: `default ${d(fb?.default_size, '—')}`,
      },
      { name: 'batch', valueType: 'int', hint: batchHint },
      {
        name: 'from',
        valueType: 'file-path',
        hint: 'sidecar YAML under mount (e.g. generated/slug/b_1.yaml); other flags override',
      },
      {
        name: 'slug',
        valueType: 'string',
        hint: 'default: auto from prompt',
      },
      {
        name: 'negative',
        valueType: 'prompt',
        hint: 'default: none',
      },
      {
        name: 'ref',
        valueType: 'file-path',
        repeatable: true,
        hint: 'reference image under mount (S3 only)',
        availability: {
          require: {
            allOf: [
              { statEq: { key: 'cloud_mount', value: true } },
              { statEq: { key: 'reference_images_supported', value: true } },
            ],
          },
        },
      },
    ],
    stats
  )
}

export const mediaModule: CommandModule = {
  commands: (stats): CommandDefinition[] => {
    if (!stats.has_mount) return []
    const attachAndManage: CommandDefinition[] = [
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
            hint: 'folder to browse, or a media file path to attach immediately',
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
            hint: 'line to insert at (attach)',
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
      {
        trigger: 'media-composite',
        group: 'narrative',
        cursorTargeting: 'never',
        hint: 'remove a chroma-keyed background — preview, tweak tolerance, then save',
        positional: [
          {
            name: 'action',
            valueType: 'slug',
            required: true,
            slugSource: 'chromakey',
            hint: 'operation (more coming later)',
          },
          {
            name: 'path',
            valueType: 'file-path',
            required: false,
            hint: 'chroma-keyed source image, or a folder to browse',
          },
        ],
        options: [
          {
            name: 'key',
            valueType: 'string',
            hint: 'hex background color, e.g. FF00FF (auto-detected if omitted)',
          },
          {
            name: 'core-tol',
            valueType: 'string',
            hint: 'tolerance override (auto-calibrated if omitted; the one worth tuning)',
          },
          {
            name: 'residual-thresh',
            valueType: 'string',
            hint: 'edge alpha-blend fit tolerance (default 10.0)',
          },
          {
            name: 'dilate-px',
            valueType: 'int',
            hint: 'edge zone width in pixels (auto-scaled if omitted)',
          },
        ],
      },
    ]
    const gen: CommandDefinition[] =
      (stats.image_backends?.length ?? 0) > 0
        ? [
            {
              trigger: 'media-generate',
              group: 'narrative',
              cursorTargeting: 'never',
              hint: mediaGenerateCommandHint(stats),
              positional: [
                {
                  name: 'prompt',
                  valueType: 'prompt',
                  required: false,
                  hint: 'image prompt (omit if using --from)',
                },
              ],
              options: mediaGenerateOptions(stats),
            },
          ]
        : []
    return [...attachAndManage, ...gen]
  },
  handler: mediaHandler,
}