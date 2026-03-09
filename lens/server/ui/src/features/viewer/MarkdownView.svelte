<script lang="ts">
  import MarkdownIt from 'markdown-it'
  import { nodeContent } from '../../stores/document'

  // html: true so that <!-- comments --> are rendered as real HTML comments
  // (invisible in browser) rather than as literal text. Safe for a private
  // single-user tool — content comes from our own backend.
  const md = new MarkdownIt({ html: true, linkify: true, typographer: true })

  $: rendered = $nodeContent ? md.render($nodeContent) : ''
</script>

<article data-testid="markdown-view" class="content">
  {#if rendered}
    {@html rendered}
  {:else}
    <p class="empty-state">Select a node from the tree.</p>
  {/if}
</article>
