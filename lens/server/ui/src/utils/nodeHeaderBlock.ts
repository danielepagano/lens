import { parse as parseYaml } from 'yaml'

export type LocalParamPill = { scope: string; name: string; value: string }

export type ParsedNodeHeader = {
  pins: string[]
  unpins: string[]
  varsEntries: [string, string][]
  paramPills: LocalParamPill[]
}

function formatParamValue(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function flattenLocalParams(params: unknown): LocalParamPill[] {
  if (!params || typeof params !== 'object' || Array.isArray(params)) return []
  const o = params as Record<string, unknown>
  const out: LocalParamPill[] = []
  const g = o.global
  if (g && typeof g === 'object' && !Array.isArray(g)) {
    for (const [name, val] of Object.entries(g as Record<string, unknown>)) {
      const value = formatParamValue(val)
      if (value !== '') out.push({ scope: 'global', name, value })
    }
  }
  for (const [slug, section] of Object.entries(o)) {
    if (slug === 'global') continue
    if (section && typeof section === 'object' && !Array.isArray(section)) {
      for (const [name, val] of Object.entries(section as Record<string, unknown>)) {
        const value = formatParamValue(val)
        if (value !== '') out.push({ scope: slug, name, value })
      }
    }
  }
  return out
}

function normalizeKbIdList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.map((x) => String(x)).filter(Boolean)
}

function legacyPinsFromRawBlockLines(blockLines: string[]): { pins: string[]; unpins: string[] } {
  const lines = blockLines.map((l) => l.replace(/^\s+/, ''))
  const pins: string[] = []
  const unpins: string[] = []
  let mode: 'none' | 'pin' | 'unpin' = 'none'
  for (const raw of lines) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    if (line.startsWith('kb_pin:')) {
      mode = 'pin'
      const inline = line.match(/kb_pin:\s*\[(.+)]/)
      if (inline?.[1]) {
        inline[1]
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .forEach((id) => pins.push(id))
      }
      continue
    }
    if (line.startsWith('kb_unpin:')) {
      mode = 'unpin'
      const inline = line.match(/kb_unpin:\s*\[(.+)]/)
      if (inline?.[1]) {
        inline[1]
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .forEach((id) => unpins.push(id))
      }
      continue
    }
    if (line.startsWith('- ')) {
      const id = line.slice(2).trim()
      if (!id) continue
      if (mode === 'pin') pins.push(id)
      else if (mode === 'unpin') unpins.push(id)
    }
  }
  return { pins, unpins }
}

/** Raw lines inside the opening `[` … `]: #` block (excluding brackets), or null if no block. */
export function extractLensHeaderRawBlockLines(markdown: string): string[] | null {
  const lines = markdown.split('\n')
  const rawBlockLines: string[] = []
  let inBlock = false
  for (const rawLine of lines) {
    if (!inBlock) {
      if (/^\s*\[\s*$/.test(rawLine)) {
        inBlock = true
        continue
      }
      if (rawLine.trim() !== '') break
      continue
    }
    if (/^\s*\]:\s*#\s*$/.test(rawLine)) break
    rawBlockLines.push(rawLine)
  }
  return inBlock ? rawBlockLines : null
}

export function parseLensNodeHeaderBlock(markdown: string): ParsedNodeHeader {
  const rawLines = extractLensHeaderRawBlockLines(markdown)
  if (!rawLines || rawLines.length === 0) {
    return { pins: [], unpins: [], varsEntries: [], paramPills: [] }
  }
  const yamlText = rawLines.join('\n')
  try {
    const data = parseYaml(yamlText) as unknown
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      const d = data as Record<string, unknown>
      const pins = normalizeKbIdList(d.kb_pin)
      const unpins = normalizeKbIdList(d.kb_unpin)
      const varsEntries: [string, string][] = []
      if (d.vars && typeof d.vars === 'object' && !Array.isArray(d.vars)) {
        for (const [k, v] of Object.entries(d.vars as Record<string, unknown>)) {
          if (typeof v === 'string') varsEntries.push([k, v])
        }
      }
      varsEntries.sort((a, b) => a[0].localeCompare(b[0]))
      const paramPills = flattenLocalParams(d.params).sort(
        (a, b) => a.scope.localeCompare(b.scope) || a.name.localeCompare(b.name),
      )
      return { pins, unpins, varsEntries, paramPills }
    }
  } catch {
    /* fall through to legacy kb_pin list parsing */
  }
  const legacy = legacyPinsFromRawBlockLines(rawLines)
  return {
    pins: legacy.pins,
    unpins: legacy.unpins,
    varsEntries: [],
    paramPills: [],
  }
}
