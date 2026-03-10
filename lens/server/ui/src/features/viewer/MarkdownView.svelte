<script lang="ts">
  import { nodeContent, currentAddress } from '../../stores/document'
  import { preprocessAnnotations, createMarkdownRenderer } from '../../utils/markdown'

  // html: true so that <!-- comments --> are rendered as real HTML comments
  // (invisible in browser) rather than as literal text. Safe for a private
  // single-user tool — content comes from our own backend.
  const md = createMarkdownRenderer()

  $: rendered = $nodeContent
    ? md.render(preprocessAnnotations($nodeContent, $currentAddress))
    : ''
</script>

<article data-testid="markdown-view" class="content">
  {#if rendered}
    {@html rendered}
  {:else}
    <p class="empty-state">Select a node from the tree.</p>
  {/if}
</article>
