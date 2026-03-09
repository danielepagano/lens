<script lang="ts">
  import { onMount } from 'svelte'
  import { getTree, getNode } from '../../services/api'
  import type { TreeNode } from '../../services/api'
  import { currentAddress, nodeContent } from '../../stores/document'
  import { treeOpen } from '../../stores/ui'
  import TreeNodeComp from './TreeNode.svelte'

  let tree: TreeNode[] = []
  let error = ''

  onMount(async () => {
    try {
      tree = await getTree()
    } catch (e) {
      error = String(e)
    }
  })

  async function navigate(addr: string) {
    try {
      const data = await getNode(addr)
      currentAddress.set(data.address)
      nodeContent.set(data.content)
      treeOpen.set(false)
    } catch (e) {
      error = String(e)
    }
  }
</script>

<div class="sidebar" class:open={$treeOpen} data-testid="tree-browser">
  <div class="sidebar-header">
    <strong>Navigation</strong>
    <button class="sidebar-close" on:click={() => treeOpen.set(false)} aria-label="Close">✕</button>
  </div>
  <div class="sidebar-body">
    {#if error}
      <p class="error-state">{error}</p>
    {:else if tree.length === 0}
      <p class="empty-state">No nodes</p>
    {:else}
      <ul class="tree-list">
        {#each tree as root (root.address)}
          <TreeNodeComp node={root} onNavigate={navigate} />
        {/each}
      </ul>
    {/if}
  </div>
</div>
