<script lang="ts">
  import { onMount } from 'svelte'
  import { getTree, getStats, setActiveNarrative } from '../../services/api'
  import type { TreeNode } from '../../services/api'
  import { treeOpen, treeRefreshTrigger } from '../../stores/ui'
  import { applyStats, stats } from '../../stores/stats'
  import TreeNodeComp from './TreeNode.svelte'
  import CloseIcon from '../../components/icons/CloseIcon.svelte'

  export let navigate: (addr: string) => Promise<void>

  let tree: TreeNode[] = []
  let error = ''

  async function loadTree() {
    tree = await getTree()
  }

  $: refreshTrigger = $treeRefreshTrigger
  $: if (refreshTrigger > 0) void loadTree().catch((e) => { error = String(e) })

  onMount(async () => {
    try {
      await loadTree()
    } catch (e) {
      error = String(e)
    }
  })

  async function onNarrativeChange(e: Event) {
    const slug = (e.target as HTMLSelectElement).value
    try {
      await setActiveNarrative(slug)
      treeRefreshTrigger.update((n) => n + 1)
      const newStats = await getStats()
      applyStats(newStats)
      if (newStats.cursor) {
        await navigate(newStats.cursor)
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
    <button class="sidebar-close" on:click={() => treeOpen.set(false)} aria-label="Close">
      <CloseIcon size={18} />
    </button>
  </div>
  {#if $stats && $stats.narratives.length > 0}
    <div class="narrative-switcher">
      <select value={$stats.active_narrative} on:change={onNarrativeChange} aria-label="Active narrative">
        {#each $stats.narratives as slug (slug)}
          <option value={slug}>{slug}</option>
        {/each}
      </select>
    </div>
  {/if}
  <div class="sidebar-body">
    {#if error}
      <p class="error-state">{error}</p>
    {:else if tree.length === 0}
      <p class="empty-state">No sub-nodes</p>
    {:else}
      <ul class="tree-list tree-list-top">
        {#each tree as node, i (node.address)}
          <TreeNodeComp node={node} isRoot={i === 0} onNavigate={onNodeNavigate} />
        {/each}
      </ul>
    {/if}
  </div>
</div>
