import { fetchMountFileText } from '../../services/api'

export type PlainPreviewState = {
  path: string | null
  text: string
  error: string | null
  loading: boolean
  fetchSeq: number
}

export function createPlainPreviewState(): PlainPreviewState {
  return { path: null, text: '', error: null, loading: false, fetchSeq: 0 }
}

export async function loadPlainPreview(
  state: PlainPreviewState,
  path: string,
): Promise<PlainPreviewState> {
  const seq = state.fetchSeq + 1
  const next: PlainPreviewState = {
    ...state,
    fetchSeq: seq,
    loading: true,
    error: null,
    text: '',
  }
  try {
    const text = await fetchMountFileText(path)
    if (seq !== next.fetchSeq) return next
    return { ...next, path, text, loading: false }
  } catch (e) {
    if (seq !== next.fetchSeq) return next
    return {
      ...next,
      path,
      error: e instanceof Error ? e.message : String(e),
      loading: false,
    }
  }
}

export function resetPlainPreview(state: PlainPreviewState): PlainPreviewState {
  return {
    path: null,
    text: '',
    error: null,
    loading: false,
    fetchSeq: state.fetchSeq + 1,
  }
}
