<script lang="ts">
  import Self from './TreeNode.svelte'
  import type { TreeNode } from '../../services/api'
  import { currentAddress } from '../../stores/document'
  import { stats } from '../../stores/stats'

  type Props = {
    node: TreeNode
    onNavigate: (addr: string) => void
    isRoot?: boolean
  }

  let { node, onNavigate, isRoot = false }: Props = $props()

  let isCursor = $derived($stats?.cursor === node.address)
</script>

<li>
  <button
    class={[
      'tree-node-btn',
      {
        'tree-node-root': isRoot,
        active: $currentAddress === node.address,
        'cursor-node': isCursor
      }
    ]}
    onclick={() => onNavigate(node.address)}
    data-address={node.address}
  >
    {#if isCursor}<span class="cursor-indicator">&gt;</span>{/if}{node.key}
  </button>
  {#if node.children?.length}
    <ul class="tree-list">
      {#each node.children as child (child.address)}
        <Self node={child} {onNavigate} />
      {/each}
    </ul>
  {/if}
</li>
