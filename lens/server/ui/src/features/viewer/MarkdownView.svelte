<script lang="ts">
  import { nodeContent, currentAddress, transactionState } from '../../stores/document'
  import { cursor, effectivePinsAtCursor } from '../../stores/session'
  import {
    preprocessAnnotations,
    createMarkdownRenderer,
    buildNodeTransactionOverlay,
  } from '../../utils/markdown'

  // html: true so that <!-- comments --> are rendered as real HTML comments
  // (invisible in browser) rather than as literal text. Safe for a private
  // single-user tool — content comes from our own backend.
  const md = createMarkdownRenderer()

  $: overlay = buildNodeTransactionOverlay($transactionState, $currentAddress)

  $: isCursorNode = Boolean($currentAddress && $cursor && $currentAddress === $cursor)

  $: rendered = $nodeContent
    ? md.render(preprocessAnnotations($nodeContent, $currentAddress, overlay))
    : ''

  type FrontMatterPins = {
    pins: string[]
    unpins: string[]
  }

  function extractFrontMatterPins(markdown: string): FrontMatterPins {
    const lines = markdown.split('\n')
    const blockLines: string[] = []
    let inBlock = false

    for (const rawLine of lines) {
      const line = rawLine
      if (!inBlock) {
        if (/^\s*\[\s*$/.test(line)) {
          inBlock = true
          continue
        }
        if (line.trim() !== '') {
          break
        }
        continue
      }
      if (/^\s*\]:\s*#\s*$/.test(line)) {
        break
      }
      blockLines.push(line.replace(/^\s+/, ''))
    }

    const pins: string[] = []
    const unpins: string[] = []
    let mode: 'none' | 'pin' | 'unpin' = 'none'

    for (const raw of blockLines) {
      const line = raw.trim()
      if (!line || line.startsWith('#')) continue

      if (line.startsWith('kb_pin:')) {
        mode = 'pin'
        const inline = line.match(/kb_pin:\s*\[(.+)]/)
        if (inline && inline[1]) {
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
        if (inline && inline[1]) {
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

  $: frontMatterPins = $nodeContent ? extractFrontMatterPins($nodeContent) : { pins: [], unpins: [] }
</script>

<article data-testid="markdown-view" class="content">
  {#if rendered}
    {#if frontMatterPins.pins.length || frontMatterPins.unpins.length}
      <div class="pin-pills pin-pills-front-matter" data-testid="front-matter-pins">
        {#each frontMatterPins.pins as id}
          <span class="pin-pill">{id}</span>
        {/each}
        {#each frontMatterPins.unpins as id}
          <span class="pin-pill pin-pill-unpin">-{id}</span>
        {/each}
      </div>
    {/if}
    {@html rendered}
    {#if isCursorNode}
      <div class="cursor-indicator-preview">
        <span class="cursor-indicator">&gt;</span>
        {#if $effectivePinsAtCursor.length}
          <div class="pin-pills effective-pins" data-testid="effective-pins-at-cursor">
            {#each $effectivePinsAtCursor as id}
              <span class="pin-pill">{id}</span>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {:else}
    <p class="empty-state">Select a node from the tree.</p>
  {/if}
</article>
