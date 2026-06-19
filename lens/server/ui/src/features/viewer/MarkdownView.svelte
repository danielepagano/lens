<script lang="ts">
  import { nodeContent, currentAddress, streamingPreview } from '../../stores/document'
  import { currentProject } from '../../stores/project'
  import { stats } from '../../stores/stats'
  import {
    preprocessAnnotations,
    preprocessBlockquotePills,
    preprocessKbMarkdownLinks,
    preprocessKbReferencePills,
    preprocessThinkingTags,
    createMarkdownRenderer,
    prefixMountUrlsInRenderedHtml,
    buildNodeTransactionOverlay,
    buildAnnotationLineSet,
    buildAttachLinePickStates,
    computeValidEndLines,
    computeValidStartLines,
  } from '../../utils/markdown'
  import { syncQuoteBlockAccents } from '../../utils/quoteBlockAccent'
  import { linePickMode, linePickSelection, scrollContentToBottom, kbDiffRequest } from '../../stores/ui'
  import { getKbItem } from '../../services/api'
  import CodeMirrorEditor from '../editor/CodeMirrorEditor.svelte'
  import ViewerContextPills from './ViewerContextPills.svelte'
  import type { LinePickRowState } from '../editor/cmLinePick'
  import { tick } from 'svelte'
  import { fromAction } from 'svelte/attachments'
  import { parseKbBlocks, injectKbDiffButtons, stripKbFrontMatter } from '../../utils/kbDiffAction'
  import { parseLensNodeHeaderBlock, type ParsedNodeHeader } from '../../utils/nodeHeaderBlock'

  // html: true so that <!-- comments --> are rendered as real HTML comments
  // (invisible in browser) rather than as literal text. Safe for a private
  // single-user tool — content comes from our own backend.
  const md = createMarkdownRenderer()

  const emptyNodeHeader: ParsedNodeHeader = {
    pins: [],
    unpins: [],
    varsEntries: [],
    paramPills: [],
  }

  const overlay = $derived(
    buildNodeTransactionOverlay($stats?.transaction?.raw_diff ?? null, $currentAddress)
  )
  const isStreamingToCurrentNode = $derived(
    $streamingPreview !== null && $currentAddress === $streamingPreview.targetNode
  )
  const isCursorNode = $derived(
    Boolean($currentAddress && $stats?.cursor && $currentAddress === $stats.cursor)
  )
  const pcKeys = $derived(
    new Set(
    ($stats?.effective_pins_at_cursor ?? [])
      .filter((id) => id.startsWith('pc.'))
      .map((id) => id.slice(3).toLowerCase()),
  )
  )
  const rememberPins = $derived($stats?.remember_pins_at_cursor ?? {})
  const rawRendered = $derived(
    $nodeContent
    ? md.render(
        preprocessThinkingTags(
          preprocessAnnotations(
            preprocessKbReferencePills(
              preprocessKbMarkdownLinks(
                preprocessBlockquotePills($nodeContent),
              ),
              rememberPins,
            ),
            $currentAddress,
            overlay,
          ),
        ),
      )
    : ''
  )
  const rendered = $derived(prefixMountUrlsInRenderedHtml(rawRendered, $currentProject))
  const nodeHeader = $derived(
    $nodeContent ? parseLensNodeHeaderBlock($nodeContent) : emptyNodeHeader
  )

  function openKbItem(id: string) {
    const base = [$currentProject, $currentAddress || ''].filter(Boolean).join('/')
    window.location.hash = `${base}?kb=${encodeURIComponent(id)}`
  }

  const isLinePicking = $derived(
    $linePickMode !== null && $linePickMode.address === $currentAddress
  )

  let contentEl: HTMLElement | null = null

  $effect(() => {
    const scrollTrigger = $scrollContentToBottom
    if (scrollTrigger <= 0 || !contentEl) return
    tick().then(() => {
      if (contentEl) contentEl.scrollTo({ top: contentEl.scrollHeight, behavior: 'smooth' })
    })
  })

  const kbBlockMap = $derived($nodeContent ? parseKbBlocks($nodeContent) : new Map<string, string>())

  async function handleMarkdownClick(e: MouseEvent) {
    const pinEl = (e.target as HTMLElement).closest('[data-kb-open-id]')
    if (pinEl) {
      e.preventDefault()
      const id = pinEl.getAttribute('data-kb-open-id')
      if (id) openKbItem(id)
      return
    }
    // Intercept hash-only anchor links (narrative navigation) and prepend project slug.
    const anchor = (e.target as HTMLElement).closest('a[href]') as HTMLAnchorElement | null
    if (anchor) {
      const href = anchor.getAttribute('href') ?? ''
      if (href.startsWith('#')) {
        const target = href.slice(1)
        // If target already starts with the project slug, let browser handle it.
        const slug = $currentProject ?? ''
        if (slug && !target.startsWith(slug + '/') && target !== slug) {
          e.preventDefault()
          window.location.hash = target ? `${slug}/${target}` : slug
        }
        return
      }
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

  const linePickLineStatesMap = $derived.by((): Map<number, LinePickRowState> | null => {
    if (!isLinePicking || !$nodeContent) return null
    const mode = $linePickMode!
    const annoSet = buildAnnotationLineSet($nodeContent)
    const m = new Map<number, LinePickRowState>()
    if (mode.operatorMode === 'attach') {
      return buildAttachLinePickStates($nodeContent)
    }
    if (mode.startLine != null && mode.operatorMode === 'edit') {
      const validEnds = computeValidEndLines($nodeContent, mode.startLine)
      $nodeContent.split('\n').forEach((_, i) => {
        const lineNo = i + 1
        m.set(
          lineNo,
          annoSet.has(lineNo) ? 'annotation' : validEnds.has(lineNo) ? 'pickable' : 'disabled',
        )
      })
      return m
    }
    const validStarts = mode.operatorMode === 'edit' ? computeValidStartLines($nodeContent) : null
    $nodeContent.split('\n').forEach((_, i) => {
      const lineNo = i + 1
      const isAnno = annoSet.has(lineNo)
      const pick = isAnno ? false : validStarts ? validStarts.has(lineNo) : true
      m.set(lineNo, isAnno ? 'annotation' : pick ? 'pickable' : 'disabled')
    })
    return m
  })
</script>

<article
  data-testid="markdown-view"
  class={[
    'content',
    {
      'content-line-picking': isLinePicking,
    },
  ]}
  bind:this={contentEl}
>
  {#if $currentAddress}
    <ViewerContextPills
      placement="header"
      header={nodeHeader}
      stats={$stats}
      {isCursorNode}
      rememberPins={rememberPins}
      onOpenKb={openKbItem}
    />
    {#if isLinePicking && linePickLineStatesMap}
      <div class="line-picker" data-testid="line-picker">
        <CodeMirrorEditor
          content={$nodeContent ?? ''}
          lang="plain"
          linePickLineStates={linePickLineStatesMap}
          onLinePick={(line) => linePickSelection.set(line)}
        />
      </div>
    {:else}
      {#if rendered}
        <div
          class="markdown-html-root"
          role="presentation"
          {@attach fromAction(syncQuoteBlockAccents, () => ({ key: rendered, pcKeys }))}
          {@attach fromAction(injectKbDiffButtons, () => rendered)}
          onclick={handleMarkdownClick}
        >
          <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
          {@html rendered}
        </div>
      {/if}
      <ViewerContextPills
        placement="cursor"
        header={nodeHeader}
        stats={$stats}
        {isCursorNode}
        rememberPins={rememberPins}
        onOpenKb={openKbItem}
      />
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
