export type VnTtsSegKind = 'text' | 'inline'
export type VnTtsSeg = { key: number; kind: VnTtsSegKind; text: string; className: string }

const ATTRIBUTED_LINE_RE = /^(\s*(?:>\s*)+)\[([^\]]+)\]\s+(.*)$/s
const TTS_MARKUP_RE = /(<\/?[a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*)*>)|(\[[a-z][a-z0-9-]*\])/gi

type VnTtsStyleFlags = { italic?: boolean; bold?: boolean; size?: 'small' | 'large' }

function wrapStyleForTagName(tagName: string): VnTtsStyleFlags {
  const t = tagName.toLowerCase()
  if (t.includes('whisper') || t.includes('soft') || t.includes('quiet')) return { italic: true, size: 'small' }
  if (t.includes('loud') || t.includes('shout') || t.includes('yell')) return { bold: true, size: 'large' }
  if (t.includes('emphasis') || t.includes('emph') || t.includes('stress')) return { italic: true, bold: true }
  if (t.includes('slow') || t.includes('drawl')) return { italic: true, size: 'large' }
  if (t.includes('fast') || t.includes('quick') || t.includes('rapid')) return { italic: true, size: 'small' }
  if (t.includes('higher') || t.includes('high') || (t.includes('pitch') && !t.includes('low'))) {
    return { italic: true, size: 'small' }
  }
  if (t.includes('lower') || t.includes('low')) return { bold: true, size: 'large' }
  if (t.includes('build') || t.includes('intens')) return { bold: true, size: 'large' }
  if (t.includes('decrease') || t.includes('fade') || t.includes('calm')) return { italic: true, size: 'small' }
  if (t.includes('sing')) return { italic: true, size: 'large' }
  if (t.includes('laugh') || t.includes('giggle') || t.includes('chuckle')) return { italic: true, size: 'small' }
  return { italic: true }
}

function stripLeadingBlockquoteMarks(line: string): string {
  let s = line
  while (s.trimStart().startsWith('>')) {
    const ix = s.indexOf('>')
    s = s.slice(ix + 1)
    if (s.startsWith(' ')) s = s.slice(1)
  }
  return s
}

export function extractDisplayBody(source: string): string {
  const lines = source.split('\n')
  const first = lines[0] ?? ''
  const m = first.match(ATTRIBUTED_LINE_RE)
  if (m?.[3] !== undefined) {
    const firstRest = m[3]
    const rest = lines.slice(1).map(stripLeadingBlockquoteMarks)
    return [firstRest, ...rest].join('\n').trimEnd()
  }
  return lines.map(stripLeadingBlockquoteMarks).join('\n').trimEnd()
}

function classNameForWrapStack(stack: string[]): string {
  let italic = false
  let bold = false
  let size: 'small' | 'large' | null = null
  for (const t of stack) {
    const s = wrapStyleForTagName(t)
    italic ||= Boolean(s.italic)
    bold ||= Boolean(s.bold)
    if (s.size === 'large') size = 'large'
    else if (s.size === 'small' && size !== 'large') size = 'small'
  }
  const classes: string[] = []
  if (italic) classes.push('vn-tts-italic')
  if (bold) classes.push('vn-tts-bold')
  if (size === 'small') classes.push('vn-tts-small')
  if (size === 'large') classes.push('vn-tts-large')
  return classes.join(' ')
}

function normalizeAngleTagName(tag: string): string {
  const raw = tag.startsWith('</') ? tag.slice(2, -1) : tag.slice(1, -1)
  return raw.trim().replace(/\s+/g, ' ').toLowerCase()
}

export function segmentTtsMarkup(source: string): VnTtsSeg[] {
  const segs: VnTtsSeg[] = []
  const stack: string[] = []
  let last = 0
  let key = 0

  for (const m of source.matchAll(TTS_MARKUP_RE)) {
    const i = m.index ?? 0
    if (i > last) {
      const text = source.slice(last, i)
      if (text) segs.push({ key: key++, kind: 'text', text, className: classNameForWrapStack(stack) })
    }
    const angle = m[1]
    if (angle) {
      const isClose = angle.startsWith('</')
      const name = normalizeAngleTagName(angle)
      if (isClose) {
        const ix = stack.lastIndexOf(name)
        if (ix !== -1) stack.splice(ix, stack.length - ix)
      } else {
        stack.push(name)
      }
    }
    last = i + (m[0]?.length ?? 0)
  }

  if (last < source.length) {
    const text = source.slice(last)
    if (text) segs.push({ key: key++, kind: 'text', text, className: classNameForWrapStack(stack) })
  }

  return segs
}
