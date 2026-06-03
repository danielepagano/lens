import type { Attachment } from 'svelte/attachments'
import {
  createMarkdownRenderer,
  preprocessBlockquotePills,
  preprocessKbReferencePills,
  prefixMountUrlsInRenderedHtml,
} from '../../utils/markdown'

const md = createMarkdownRenderer({ openLinksInNewTab: true })

export function renderKbMarkdown(
  content: string,
  rememberPinsAtCursor: Readonly<Record<string, string[]>> | null | undefined,
  projectSlug: string | null,
): string {
  const raw = md.render(
    preprocessKbReferencePills(preprocessBlockquotePills(content), rememberPinsAtCursor),
  )
  return prefixMountUrlsInRenderedHtml(raw, projectSlug)
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
