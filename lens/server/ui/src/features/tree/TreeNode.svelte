<script lang="ts">
  import type { TreeNode } from '../../services/api'
  import { currentAddress } from '../../stores/document'
  import { cursor } from '../../stores/session'

  export let node: TreeNode
  export let onNavigate: (addr: string) => void

  $: isCursor = $cursor === node.address
</script>

<li>
  <button
    class="tree-node-btn"
    class:active={$currentAddress === node.address}
    class:cursor-node={isCursor}
    on:click={() => onNavigate(node.address)}
    data-address={node.address}
  >
    {node.key}{#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}
  </button>
  {#if node.children?.length}
    <ul class="tree-list">
      {#each node.children as child (child.address)}
        <svelte:self node={child} {onNavigate} />
      {/each}
    </ul>
  {/if}
</li>
