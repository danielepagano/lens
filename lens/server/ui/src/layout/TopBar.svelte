<script lang="ts">
  import { currentAddress } from '../stores/document'
  import { treeOpen } from '../stores/ui'
</script>

<header class="top-bar" data-testid="top-bar">
  <button class="tree-toggle" on:click={() => treeOpen.update(v => !v)} aria-label="Toggle tree">
    ☰
  </button>
  <span class="title">Lens</span>
  {#if $currentAddress}
    <span class="address">{$currentAddress}</span>
  {/if}
</header>
