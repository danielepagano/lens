<script lang="ts">
  import type { Snippet } from 'svelte'

  type Props = {
    topbar?: Snippet
    children?: Snippet
    bottombar?: Snippet
  }
  let { topbar, children, bottombar }: Props = $props()
</script>

<div class="layout">
  {@render topbar?.()}
  <div class="main-area">
    {@render children?.()}
  </div>
  {@render bottombar?.()}
</div>
