<script lang="ts">
  import { nodeContent, currentAddress, transactionState } from '../../stores/document'
  import { cursor } from '../../stores/session'
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
</script>

<article data-testid="markdown-view" class="content">
  {#if rendered}
    {@html rendered}
    {#if isCursorNode}
      <div class="cursor-indicator-preview">
        <span class="cursor-indicator">&gt;</span>
      </div>
    {/if}
  {:else}
    <p class="empty-state">Select a node from the tree.</p>
  {/if}
</article>
