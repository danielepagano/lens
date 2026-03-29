<script lang="ts">
  import { nodeContent, currentAddress, streamingPreview } from '../../stores/document'
  import { stats } from '../../stores/stats'
  import {
    preprocessAnnotations,
    preprocessBlockquotePills,
    preprocessKbReferencePills,
    preprocessThinkingTags,
    createMarkdownRenderer,
    buildNodeTransactionOverlay,
    buildAnnotationLineSet,
    computeValidEndLines,
    computeValidStartLines,
  } from '../../utils/markdown'
  import { syncQuoteBlockAccents } from '../../utils/quoteBlockAccent'
  import { linePickMode, linePickSelection, scrollContentToBottom, kbDiffRequest } from '../../stores/ui'
  import { getKbItem } from '../../services/api'
  import CodeMirrorEditor from '../editor/CodeMirrorEditor.svelte'
  import type { LinePickRowState } from '../editor/cmLinePick'
  import { tick } from 'svelte'
  import { parseKbBlocks, injectKbDiffButtons, stripKbFrontMatter } from '../../utils/kbDiffAction'

  // html: true so that <!-- comments --> are rendered as real HTML comments
  // (invisible in browser) rather than as literal text. Safe for a private
  // single-user tool — content comes from our own backend.
  const md = createMarkdownRenderer()

  $: overlay = buildNodeTransactionOverlay($stats?.transaction?.raw_diff ?? null, $currentAddress)

  $: isStreamingToCurrentNode =
    $streamingPreview !== null && $currentAddress === $streamingPreview.targetNode

  $: isCursorNode = Boolean($currentAddress && $stats?.cursor && $currentAddress === $stats.cursor)

  $: pcKeys = new Set(
    ($stats?.effective_pins_at_cursor ?? [])
      .filter((id) => id.startsWith('pc.'))
      .map((id) => id.slice(3).toLowerCase()),
  )

  $: rendered = $nodeContent
    ? md.render(
        preprocessThinkingTags(
          preprocessAnnotations(
            preprocessKbReferencePills(preprocessBlockquotePills($nodeContent)),
            $currentAddress,
            overlay,
          ),
        ),
      )
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

  let contentEl: HTMLElement | null = null

  $: _scrollTrigger = $scrollContentToBottom
  $: if (_scrollTrigger > 0 && contentEl) {
    tick().then(() => {
      if (contentEl) contentEl.scrollTo({ top: contentEl.scrollHeight, behavior: 'smooth' })
    })
  }

  $: kbBlockMap = $nodeContent ? parseKbBlocks($nodeContent) : new Map<string, string>()

  async function handleMarkdownClick(e: MouseEvent) {
    const pinEl = (e.target as HTMLElement).closest('[data-kb-open-id]')
    if (pinEl) {
      const id = pinEl.getAttribute('data-kb-open-id')
      if (id) openKbItem(id)
      return
    }
    const btn = (e.target as HTMLElement).closest('[data-kb-id]') as HTMLButtonElement | null
    if (!btn) return
    const kbId = btn.dataset.kbId
    if (!kbId) return
    const proposed = kbBlockMap.get(kbId) ?? ''
    btn.textContent = 'Loading…'
    btn.disabled = true
    try {
      const item = await getKbItem(kbId)
      const strippedProposed = stripKbFrontMatter(proposed)
      if (item.content.trim() === strippedProposed.trim()) {
        btn.textContent = 'No Change'
        btn.classList.add('kb-diff-btn--no-change')
      } else {
        kbDiffRequest.set({ kbId, proposed: strippedProposed, current: item.content })
        btn.textContent = 'Show Diff'
      }
    } catch (err) {
      if (String(err).includes('404')) {
        btn.textContent = 'New Item'
        btn.classList.add('kb-diff-btn--new-item')
      } else {
        btn.textContent = 'Error'
        console.error('KB diff fetch error:', err)
      }
    } finally {
      btn.disabled = false
    }
  }

  $: linePickLineStatesMap = ((): Map<number, LinePickRowState> | null => {
    if (!isLinePicking || !$nodeContent) return null
    const mode = $linePickMode!
    const annoSet = buildAnnotationLineSet($nodeContent)
    const m = new Map<number, LinePickRowState>()
    if (mode.startLine != null && mode.operatorMode) {
      const validEnds = computeValidEndLines($nodeContent, mode.startLine, mode.operatorMode)
      $nodeContent.split('\n').forEach((_, i) => {
        const lineNo = i + 1
        m.set(
          lineNo,
          annoSet.has(lineNo) ? 'annotation' : validEnds.has(lineNo) ? 'pickable' : 'disabled',
        )
      })
      return m
    }
    const validStarts = mode.operatorMode
      ? computeValidStartLines($nodeContent, mode.operatorMode)
      : null
    $nodeContent.split('\n').forEach((_, i) => {
      const lineNo = i + 1
      const isAnno = annoSet.has(lineNo)
      const pick = isAnno ? false : validStarts ? validStarts.has(lineNo) : true
      m.set(lineNo, isAnno ? 'annotation' : pick ? 'pickable' : 'disabled')
    })
    return m
  })()
</script>

<article
  data-testid="markdown-view"
  class="content"
  class:content-line-picking={isLinePicking}
  bind:this={contentEl}
>
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
    {#if isLinePicking && linePickLineStatesMap}
      <div class="line-picker" data-testid="line-picker">
        <CodeMirrorEditor
          content={$nodeContent ?? ''}
          lang="plain"
          linePickLineStates={linePickLineStatesMap}
          on:linePick={(e) => linePickSelection.set(e.detail)}
        />
      </div>
    {:else}
      {#if rendered}
        <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
        <div
          class="markdown-html-root"
          use:syncQuoteBlockAccents={{ key: rendered, pcKeys }}
          use:injectKbDiffButtons={rendered}
          on:click={handleMarkdownClick}
        >
          <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
          {@html rendered}
        </div>
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
