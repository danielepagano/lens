import { get } from 'svelte/store'
import { mediaCompositeSession, type MediaCompositeParams } from '../../stores/ui'
import { previewChromakey, saveChromakey } from '../../services/api'

export function parseNumberInput(raw: string): number | undefined {
  const t = raw.trim()
  if (!t) return undefined
  const n = Number(t)
  return Number.isFinite(n) ? n : undefined
}

export interface ChromakeyOverrideInputs {
  key: string
  coreTol: string
  residualThresh: string
  dilatePx: string
}

export function buildChromakeyParams(
  path: string,
  inputs: ChromakeyOverrideInputs
): MediaCompositeParams {
  const key = inputs.key.trim()
  const coreTol = parseNumberInput(inputs.coreTol)
  const residualThresh = parseNumberInput(inputs.residualThresh)
  const dilatePx = parseNumberInput(inputs.dilatePx)
  return {
    path,
    ...(key ? { key } : {}),
    ...(coreTol !== undefined ? { coreTol } : {}),
    ...(residualThresh !== undefined ? { residualThresh } : {}),
    ...(dilatePx !== undefined ? { dilatePx } : {}),
  }
}

export function startChromakeySession(path: string): void {
  mediaCompositeSession.set({
    path,
    status: 'previewing',
    lastParams: null,
    previewSrc: null,
    keyHex: null,
    coreTol: null,
    residualThresh: null,
    dilatePx: null,
    nCornersUsed: null,
    error: null,
    savedPath: null,
  })
}

export async function runChromakeyPreview(params: MediaCompositeParams): Promise<void> {
  mediaCompositeSession.update((s) => (s ? { ...s, status: 'previewing', error: null } : s))
  try {
    const result = await previewChromakey(params)
    mediaCompositeSession.update((s) =>
      s
        ? {
            ...s,
            status: 'ready',
            lastParams: params,
            previewSrc: `data:image/png;base64,${result.png_b64}`,
            keyHex: result.key_hex,
            coreTol: result.core_tol,
            residualThresh: result.residual_thresh,
            dilatePx: result.dilate_px,
            nCornersUsed: result.n_corners_used,
            savedPath: null,
          }
        : s
    )
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    mediaCompositeSession.update((s) => (s ? { ...s, status: 'error', error: message } : s))
  }
}

export async function runChromakeySave(): Promise<void> {
  const session = get(mediaCompositeSession)
  if (!session || !session.lastParams || session.previewSrc === null) return
  mediaCompositeSession.update((s) => (s ? { ...s, status: 'saving', error: null } : s))
  try {
    const result = await saveChromakey(session.lastParams)
    mediaCompositeSession.update((s) =>
      s ? { ...s, status: 'saved', savedPath: result.output_path } : s
    )
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    mediaCompositeSession.update((s) => (s ? { ...s, status: 'error', error: message } : s))
  }
}
