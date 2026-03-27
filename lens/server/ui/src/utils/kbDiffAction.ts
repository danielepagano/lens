import { tick } from 'svelte'

/**
 * Strip YAML front matter (--- … ---) from a kb fenced block's raw content.
 * The id/name/tags metadata block is not stored as item content.
 */
export function stripKbFrontMatter(content: string): string {
  const lines = content.split('\n')
  if (lines[0]?.trim() !== '---') return content
  let end = 1
  while (end < lines.length && lines[end]?.trim() !== '---') {
    end++
  }
  // skip the closing --- and any blank lines after it
  let start = end + 1
  while (start < lines.length && lines[start]?.trim() === '') {
    start++
  }
  return lines.slice(start).join('\n').trimEnd()
}

/**
 * Parse all ```kb fenced blocks from markdown source.
 * Returns a Map of kb id → raw block content (trimmed).
 */
export function parseKbBlocks(markdown: string): Map<string, string> {
  const result = new Map<string, string>()
  const lines = markdown.split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const fenceMatch = line.match(/^\s*(`{3,}|~{3,})\s*kb\s*$/)
    if (fenceMatch) {
      const marker = fenceMatch[1][0] as '`' | '~'
      const minLen = fenceMatch[1].length
      const contentLines: string[] = []
      i++
      while (i < lines.length) {
        const inner = lines[i]
        const closerMatch = inner.match(/^\s*(`{3,}|~{3,})\s*$/)
        if (
          closerMatch &&
          closerMatch[1][0] === marker &&
          closerMatch[1].length >= minLen
        ) {
          break
        }
        contentLines.push(inner)
        i++
      }
      const content = contentLines.join('\n')
      const idMatch = content.match(/^id:\s*(\S+)/m)
      if (idMatch?.[1]) {
        result.set(idMatch[1], content.trim())
      }
    }
    i++
  }
  return result
}

/**
 * Svelte action: after each render, find all <pre><code class="language-kb"> blocks
 * and inject a "Show Diff" button below each one.
 * Buttons carry a `data-kb-id` attribute for click-delegation in the parent component.
 */
export function injectKbDiffButtons(
  node: HTMLElement,
  _rendered: string,
): { update(_rendered: string): void } {
  function inject() {
    void tick().then(() => {
      node.querySelectorAll('pre > code.language-kb').forEach((codeEl) => {
        const pre = codeEl.parentElement!
        if (pre.parentElement?.classList.contains('kb-diff-wrap')) return
        const content = codeEl.textContent ?? ''
        const idMatch = content.match(/^id:\s*(\S+)/m)
        const kbId = idMatch?.[1] ?? ''
        if (!kbId) return
        const wrap = document.createElement('div')
        wrap.className = 'kb-diff-wrap'
        pre.parentNode!.insertBefore(wrap, pre)
        wrap.appendChild(pre)
        const btn = document.createElement('button')
        btn.className = 'kb-diff-btn'
        btn.textContent = 'Show Diff'
        btn.dataset.kbId = kbId
        wrap.appendChild(btn)
      })
    })
  }

  inject()
  return {
    update() {
      // After re-render, injected wrappers are gone (innerHTML replaced). Re-inject.
      inject()
    },
  }
}
