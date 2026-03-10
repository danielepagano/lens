<script lang="ts">
  import { onMount } from 'svelte'
  import { getTree, getStats, getNarratives, setActiveNarrative } from '../../services/api'
  import type { TreeNode } from '../../services/api'
  import { treeOpen } from '../../stores/ui'
  import { activeNarrative, availableNarratives } from '../../stores/session'
  import TreeNodeComp from './TreeNode.svelte'

  export let navigate: (addr: string) => Promise<void>

  let tree: TreeNode[] = []
  let error = ''

  async function loadTree() {
    tree = await getTree()
  }

  onMount(async () => {
    try {
      const [narrativesData] = await Promise.all([getNarratives(), loadTree()])
      availableNarratives.set(narrativesData.narratives)
      activeNarrative.set(narrativesData.active)
    } catch (e) {
      error = String(e)
    }
  })

  async function onNarrativeChange(e: Event) {
    const slug = (e.target as HTMLSelectElement).value
    try {
      await setActiveNarrative(slug)
      activeNarrative.set(slug)
      await loadTree()
      const stats = await getStats()
      if (stats.cursor) {
        await navigate(stats.cursor)
      }
      treeOpen.set(false)
    } catch (err) {
      error = String(err)
    }
  }

  function onNodeNavigate(addr: string) {
    navigate(addr)
    treeOpen.set(false)
  }
</script>

<div class="sidebar" class:open={$treeOpen} data-testid="tree-browser">
  <div class="sidebar-header">
    <strong>Navigation</strong>
    <button class="sidebar-close" on:click={() => treeOpen.set(false)} aria-label="Close">✕</button>
  </div>
  {#if $availableNarratives.length > 0}
    <div class="narrative-switcher">
      <select value={$activeNarrative} on:change={onNarrativeChange} aria-label="Active narrative">
        {#each $availableNarratives as slug (slug)}
          <option value={slug}>{slug}</option>
        {/each}
      </select>
    </div>
  {/if}
  <div class="sidebar-body">
    {#if error}
      <p class="error-state">{error}</p>
    {:else if tree.length === 0}
      <p class="empty-state">No nodes</p>
    {:else}
      <ul class="tree-list">
        {#each tree as root (root.address)}
          <TreeNodeComp node={root} onNavigate={onNodeNavigate} />
        {/each}
      </ul>
    {/if}
  </div>
</div>
