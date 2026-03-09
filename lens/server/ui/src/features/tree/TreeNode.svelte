<script lang="ts">
  import type { TreeNode } from '../../services/api'
  import { currentAddress } from '../../stores/document'

  export let node: TreeNode
  export let onNavigate: (addr: string) => void
</script>

<li>
  <button
    class="tree-node-btn"
    class:active={$currentAddress === node.address}
    on:click={() => onNavigate(node.address)}
    data-address={node.address}
  >
    {node.key}
  </button>
  {#if node.children?.length}
    <ul class="tree-list">
      {#each node.children as child (child.address)}
        <svelte:self node={child} {onNavigate} />
      {/each}
    </ul>
  {/if}
</li>
