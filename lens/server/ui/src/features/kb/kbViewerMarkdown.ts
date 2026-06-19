import type { Attachment } from 'svelte/attachments'
import {
  createMarkdownRenderer,
  preprocessBlockquotePills,
  preprocessKbMarkdownLinks,
  preprocessKbReferencePills,
  prefixMountUrlsInRenderedHtml,
} from '../../utils/markdown'
import {
  preprocessKbEditableControls,
  type KbEditMeta,
} from './kbEditableControls'

const md = createMarkdownRenderer({ openLinksInNewTab: true })

export function renderKbMarkdown(
  content: string,
  rememberPinsAtCursor: Readonly<Record<string, string[]>> | null | undefined,
  projectSlug: string | null,
  enableEditableControls?: boolean,
): { html: string; editMeta: KbEditMeta[] } {
  const { body } = stripKbItemFrontMatter(content)
  const bodyOffset = content.indexOf(body)

  let processed = body
  let editMeta: KbEditMeta[] = []

  if (enableEditableControls) {
    const result = preprocessKbEditableControls(processed)
    processed = result.processed
    // Adjust offsets from body-relative to full-content-relative
    for (const m of result.editMeta) {
      m.rawStart += bodyOffset
      m.rawEnd += bodyOffset
    }
    editMeta = result.editMeta
  }

  const raw = md.render(
    preprocessKbReferencePills(
      preprocessKbMarkdownLinks(preprocessBlockquotePills(processed)),
      rememberPinsAtCursor,
    ),
  )
  return {
    html: prefixMountUrlsInRenderedHtml(raw, projectSlug),
    editMeta,
  }
}

export function kbViewerHashBase(projectSlug: string | null, address: string): string {
  return [projectSlug ?? '', address].filter(Boolean).join('/')
}

export function openKbItemInHash(viewerHashBase: string, id: string): void {
  window.location.hash = `${viewerHashBase}?kb=${encodeURIComponent(id)}`
}

export function handleKbMarkdownClick(event: MouseEvent, viewerHashBase: string): void {
  const pinEl = (event.target as HTMLElement).closest('[data-kb-open-id]')
  if (!pinEl) return
  event.preventDefault()
  const id = pinEl.getAttribute('data-kb-open-id')
  if (id) openKbItemInHash(viewerHashBase, id)
}

export function attachKbMarkdownClicks(viewerHashBase: string): Attachment<HTMLDivElement> {
  return (element) => {
    const handleClick = (event: MouseEvent) => handleKbMarkdownClick(event, viewerHashBase)
    element.addEventListener('click', handleClick)
    return () => {
      element.removeEventListener('click', handleClick)
    }
  }
}

export function openKbItemFromLinkClick(event: MouseEvent, viewerHashBase: string, id: string): void {
  event.preventDefault()
  openKbItemInHash(viewerHashBase, id)
}

const FRONT_MATTER_OPEN_RE = /^\s*\[\s*$/
const FRONT_MATTER_END_RE = /^\s*\]\s*:\s*#\s*$/

export interface KbItemFrontMatter {
  kbDetails: boolean
}

/**
 * Parse and strip KB item front matter. Returns the body (content without
 * front matter) and parsed front matter flags.
 */
export function stripKbItemFrontMatter(content: string): {
  body: string
  frontMatter: KbItemFrontMatter
} {
  const lines = content.split('\n')
  if (lines.length === 0) {
    return { body: content, frontMatter: { kbDetails: false } }
  }
  let firstLine = 0
  while (firstLine < lines.length && !lines[firstLine]!.trim()) {
    firstLine++
  }
  if (firstLine >= lines.length || !FRONT_MATTER_OPEN_RE.test(lines[firstLine]!)) {
    return { body: content, frontMatter: { kbDetails: false } }
  }

  let i = firstLine + 1
  const fm: KbItemFrontMatter = { kbDetails: false }
  while (i < lines.length && !FRONT_MATTER_END_RE.test(lines[i]!)) {
    const m = lines[i]!.trim().match(/^kb-details:\s*(true|false)$/i)
    if (m) fm.kbDetails = m[1]!.toLowerCase() === 'true'
    i++
  }
  if (i < lines.length) i++ // skip `]: #`
  while (i < lines.length && !lines[i]!.trim()) i++ // skip trailing blank lines

  return { body: lines.slice(i).join('\n'), frontMatter: fm }
}

const KB_DETAILS_RE = /^(\s*)kb-details:\s*(true|false)\s*$/i

/**
 * Toggle the `kb-details` flag in an item's front matter.  If no front matter
 * exists, one is created with `kb-details: true`.  Returns the updated full
 * content string.
 */
export function toggleKbDetailsFlag(content: string): string {
  const lines = content.split('\n')
  if (lines.length === 0) return `[\n    kb-details: true\n]: #\n\n${content}`

  let firstLine = 0
  while (firstLine < lines.length && !lines[firstLine]!.trim()) {
    firstLine++
  }
  if (firstLine < lines.length && FRONT_MATTER_OPEN_RE.test(lines[firstLine]!)) {
    let detailIndex = -1
    let endIndex = -1
    let currentValue = 'false'
    for (let i = firstLine + 1; i < lines.length; i++) {
      if (FRONT_MATTER_END_RE.test(lines[i]!)) { endIndex = i; break }
      const m = lines[i]!.match(KB_DETAILS_RE)
      if (m) { detailIndex = i; currentValue = m[2]! }
    }
    if (endIndex === -1) {
      // Malformed → wrap everything
      return `[\n    kb-details: true\n]: #\n\n${content}`
    }
    const newValue = currentValue === 'true' ? 'false' : 'true'
    if (detailIndex !== -1) {
      lines[detailIndex] = lines[detailIndex]!.replace(KB_DETAILS_RE, `$1kb-details: ${newValue}`)
    } else {
      lines.splice(endIndex, 0, '    kb-details: true')
    }
    return lines.join('\n')
  }

  return `[\n    kb-details: true\n]: #\n\n${content}`
}

/**
 * Update only the `kb-detail` param in the current URL hash, preserving all
 * other params (kb, path, etc.).
 */
export function setKbDetailParam(id: string | null): void {
  const hash = window.location.hash
  const qIndex = hash.indexOf('?')
  const base = qIndex === -1 ? hash : hash.slice(0, qIndex)
  const params = new URLSearchParams(qIndex === -1 ? '' : hash.slice(qIndex + 1))
  if (id) {
    params.set('kb-detail', id)
  } else {
    params.delete('kb-detail')
  }
  const qs = params.toString()
  window.location.hash = qs ? `${base}?${qs}` : base
}

/** Callback for KB link clicks in detail-aware mode. */
export type KbLinkHandler = (id: string) => void

/**
 * Create a click handler that intercepts `[data-kb-open-id]` elements and
 * routes them through the given handler instead of setting `?kb=` in the URL.
 * Used for detail-aware split view when
 * detail item. */
export function createDetailClickHandler(handler: KbLinkHandler): (event: MouseEvent) => void {
  return (event: MouseEvent) => {
    const pinEl = (event.target as HTMLElement).closest('[data-kb-open-id]')
    if (!pinEl) return
    event.preventDefault()
    const id = pinEl.getAttribute('data-kb-open-id')
    if (id) handler(id)
  }
}

/**
 * Svelte attachment for detail-aware click handling.  Intercepts
 * `[data-kb-open-id]` clicks and routes through `handler` rather than
 * navigating the main `?kb=` hash param.
 */
export function attachKbDetailClicks(handler: KbLinkHandler): Attachment<HTMLDivElement> {
  return (element) => {
    const handleClick = createDetailClickHandler(handler)
    element.addEventListener('click', handleClick)
    return () => element.removeEventListener('click', handleClick)
  }
}
