import type { VnTtsSettings } from './vnTypes'
import { DEFAULT_VN_TTS } from './vnTypes'

export interface ParsedAppHash {
  project: string | null
  path: string
  kb: string | null
  kbDetail: string | null
  vn: boolean
  /** Scene step: user-visible beat index (text / orphan image), not raw `PlaybackItem` index. */
  vn_i: number
  /** True when `vn_i` query key was present (even if 0). */
  vn_i_explicit: boolean
  /** Resolved TTS flags (defaults applied when URL omits them). */
  vnTts: VnTtsSettings
  /** True when URL explicitly set any Scene TTS query key (including legacy `vn_tts`). */
  vnTtsFromUrl: boolean
}

function splitHashRaw(hash: string): { pathPart: string; query: URLSearchParams } {
  if (!hash || hash === '#') return { pathPart: '', query: new URLSearchParams() }
  const raw = decodeURIComponent(hash.slice(1))
  const qIndex = raw.indexOf('?')
  if (qIndex === -1) return { pathPart: raw, query: new URLSearchParams() }
  return {
    pathPart: raw.slice(0, qIndex),
    query: new URLSearchParams(raw.slice(qIndex + 1)),
  }
}

function parseVnTtsFromQuery(query: URLSearchParams): {
  settings: VnTtsSettings | null
  fromUrl: boolean
} {
  const legacy = query.get('vn_tts')
  const hasLegacy = legacy === 'off' || legacy === 'cached' || legacy === 'auto'
  /** `vn_spk=0` is explicit TTS off (must not fall back to session). */
  if (query.has('vn_spk')) {
    return {
      settings: {
        speak: query.get('vn_spk') === '1',
        autoAdvance: query.get('vn_aa') === '1',
        renderNew: query.get('vn_rdr') === '1',
      },
      fromUrl: true,
    }
  }
  const hasSubflags = query.has('vn_aa') || query.has('vn_rdr')
  if (hasSubflags) {
    return {
      settings: {
        speak: true,
        autoAdvance: query.get('vn_aa') === '1',
        renderNew: query.get('vn_rdr') === '1',
      },
      fromUrl: true,
    }
  }

  if (hasLegacy) {
    if (legacy === 'cached') {
      return {
        settings: { speak: true, autoAdvance: false, renderNew: false },
        fromUrl: true,
      }
    }
    if (legacy === 'auto') {
      return {
        settings: { speak: true, autoAdvance: true, renderNew: true },
        fromUrl: true,
      }
    }
    return { settings: { ...DEFAULT_VN_TTS }, fromUrl: true }
  }

  return { settings: null, fromUrl: false }
}

/**
 * Parse `#project/narrative/path?...` the same way as [App.svelte] init, plus VN query params.
 */
export function parseAppHash(hash: string): ParsedAppHash {
  const { pathPart, query } = splitHashRaw(hash)
  const stripped = pathPart.startsWith('/') ? pathPart.slice(1) : pathPart
  const slashIdx = stripped.indexOf('/')
  const project = slashIdx === -1 ? (stripped || null) : stripped.slice(0, slashIdx)
  const path = slashIdx === -1 ? '' : stripped.slice(slashIdx + 1)

  const kb = query.get('kb')
  const kbDetailRaw = query.get('kb-detail')
  const kbDetail = kbDetailRaw && kbDetailRaw.length > 0 ? kbDetailRaw : null
  const vn = query.get('vn') === '1'
  const vn_i_explicit = query.has('vn_i')
  const vn_i_raw = query.get('vn_i')
  let vn_i = 0
  if (vn_i_raw !== null && vn_i_raw !== '') {
    const n = parseInt(vn_i_raw, 10)
    if (!Number.isNaN(n) && n >= 0) vn_i = n
  }

  const { settings: ttsParsed, fromUrl: vnTtsFromUrl } = parseVnTtsFromQuery(query)
  const vnTts = ttsParsed ?? { ...DEFAULT_VN_TTS }

  return {
    project,
    path,
    kb: kb && kb.length > 0 ? kb : null,
    kbDetail,
    vn,
    vn_i,
    vn_i_explicit,
    vnTts,
    vnTtsFromUrl,
  }
}

export interface BuildAppHashOpts {
  kb?: string | null
  kbDetail?: string | null
  vn?: boolean
  vn_i?: number
  vnTts?: VnTtsSettings
}

/** Build hash fragment without leading `#`. When `vn` is true, `kb` is omitted. */
export function buildAppHash(slug: string, narrativePath: string, opts: BuildAppHashOpts = {}): string {
  const base = narrativePath ? `${slug}/${narrativePath}` : slug
  const params = new URLSearchParams()

  if (opts.vn) {
    params.set('vn', '1')
    params.set('vn_i', String(opts.vn_i ?? 0))
    const t = opts.vnTts ?? { ...DEFAULT_VN_TTS }
    params.set('vn_spk', t.speak ? '1' : '0')
    if (t.speak) {
      if (t.autoAdvance) params.set('vn_aa', '1')
      if (t.renderNew) params.set('vn_rdr', '1')
    }
  } else {
    if (opts.kb) params.set('kb', opts.kb)
    if (opts.kbDetail) params.set('kb-detail', opts.kbDetail)
  }

  const q = params.toString()
  return q ? `${base}?${q}` : base
}

/**
 * Hash fragment (no leading `#`) after `getNode` during init/navigation when the browser
 * already pointed at this project + path. Preserves Scene (`vn*`) query params so refresh
 * keeps beat index and TTS flags.
 */
export function hashAfterNodeResolved(
  slug: string,
  resolvedAddress: string,
  kb: string | null,
  currentHash: string
): string {
  const parsed = parseAppHash(currentHash)
  if (parsed.vn && parsed.project === slug && parsed.path === resolvedAddress) {
    return buildAppHash(slug, resolvedAddress, {
      vn: true,
      vn_i: parsed.vn_i,
      vnTts: parsed.vnTts,
    })
  }
  const parsedKbDetail = parsed.kbDetail
  const k = kb && kb.length > 0 ? kb : undefined
  return buildAppHash(slug, resolvedAddress, { kb: k, kbDetail: parsedKbDetail })
}
