<script lang="ts">
  import { nodeContent, currentAddress, streamingPreview } from '../../stores/document'
  import { stats } from '../../stores/stats'
  import {
    preprocessAnnotations,
    createMarkdownRenderer,
    buildNodeTransactionOverlay,
    buildAnnotationLineSet,
  } from '../../utils/markdown'
  import { linePickMode, linePickSelection } from '../../stores/ui'

  // html: true so that <!-- comments --> are rendered as real HTML comments
  // (invisible in browser) rather than as literal text. Safe for a private
  // single-user tool — content comes from our own backend.
  const md = createMarkdownRenderer()

  $: overlay = buildNodeTransactionOverlay($stats?.transaction?.raw_diff ?? null, $currentAddress)

  $: isStreamingToCurrentNode =
    $streamingPreview !== null && $currentAddress === $streamingPreview.targetNode

  $: isCursorNode = Boolean($currentAddress && $stats?.cursor && $currentAddress === $stats.cursor)

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

  function openKbItem(id: string) {
    const path = $currentAddress || ''
    window.location.hash = `${path}?kb=${encodeURIComponent(id)}`
  }

  $: isLinePicking = $linePickMode !== null && $linePickMode.address === $currentAddress

  $: sourceLines = (() => {
    if (!isLinePicking || !$nodeContent) return []
    const annoSet = buildAnnotationLineSet($nodeContent)
    return $nodeContent.split('\n').map((text, i) => ({
      lineNo: i + 1,
      text,
      pickable: !annoSet.has(i + 1),
    }))
  })()
</script>

<article data-testid="markdown-view" class="content">
  {#if $currentAddress}
    {#if frontMatterPins.pins.length || frontMatterPins.unpins.length}
      <div class="pin-pills pin-pills-front-matter" data-testid="front-matter-pins">
        {#each frontMatterPins.pins as id (id)}
          <button class="pin-pill" on:click={() => openKbItem(id)}>{id}</button>
        {/each}
        {#each frontMatterPins.unpins as id (id)}
          <button class="pin-pill pin-pill-unpin" on:click={() => openKbItem(id)}>-{id}</button>
        {/each}
      </div>
    {/if}
    {#if isLinePicking}
      <div class="line-picker" data-testid="line-picker">
        {#each sourceLines as { lineNo, text, pickable } (lineNo)}
          <div
            class="line-row"
            class:pickable
            class:annotation={!pickable}
            role={pickable ? 'button' : 'presentation'}
            tabindex={pickable ? 0 : -1}
            on:click={() => pickable && linePickSelection.set(lineNo)}
            on:keydown={(e) => { if (pickable && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); linePickSelection.set(lineNo) } }}
          >
            <span class="line-number">{lineNo}</span><span class="line-text">{text || '\u00a0'}</span>
          </div>
        {/each}
      </div>
    {:else}
      {#if rendered}
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
        {@html rendered}
      {/if}
      {#if isCursorNode}
        <div class="cursor-indicator-preview">
          <span class="cursor-indicator">&gt;</span>
          {#if $stats?.effective_pins_at_cursor?.length}
            <div class="pin-pills effective-pins" data-testid="effective-pins-at-cursor">
              {#each $stats.effective_pins_at_cursor as id (id)}
                <button class="pin-pill" on:click={() => openKbItem(id)}>{id}</button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
      {#if isStreamingToCurrentNode && $streamingPreview}
        <div class="transaction-added streaming-preview" data-testid="streaming-preview">
          <code>{$streamingPreview.text}</code>
        </div>
      {/if}
    {/if}
  {:else}
    <p class="empty-state">Select a node from the tree.</p>
  {/if}
</article>
