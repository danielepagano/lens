<script lang="ts">
  import { onMount } from 'svelte'
  import { getTree, getStats, setActiveNarrative } from '../../services/api'
  import type { TreeNode } from '../../services/api'
  import { treeOpen, treeRefreshTrigger, scrollContentToBottom } from '../../stores/ui'
  import { applyStats, stats } from '../../stores/stats'
  import TreeNodeComp from './TreeNode.svelte'
  import CloseIcon from '../../components/icons/CloseIcon.svelte'

  export let navigate: (addr: string) => Promise<void>

  let tree: TreeNode[] = []
  let error = ''

  let createDialog: HTMLDialogElement | undefined
  let newNarrativeSlug = ''
  let createNarrativeError = ''
  let createNarrativeBusy = false

  const SLUG_RE = /^[a-zA-Z0-9_-]+$/

  function openCreateNarrativeDialog() {
    newNarrativeSlug = ''
    createNarrativeError = ''
    createDialog?.showModal()
  }

  function closeCreateNarrativeDialog() {
    createNarrativeBusy = false
    createDialog?.close()
  }

  async function submitNewNarrative() {
    const slug = newNarrativeSlug.trim()
    if (!slug) {
      createNarrativeError = 'Name cannot be empty.'
      return
    }
    if (!SLUG_RE.test(slug)) {
      createNarrativeError = 'Use only letters, numbers, underscores, and hyphens.'
      return
    }
    createNarrativeError = ''
    createNarrativeBusy = true
    try {
      await setActiveNarrative(slug)
      treeRefreshTrigger.update((n) => n + 1)
      const newStats = await getStats()
      applyStats(newStats)
      if (newStats.cursor) {
        await navigate(newStats.cursor)
      }
      closeCreateNarrativeDialog()
      treeOpen.set(false)
    } catch (err) {
      createNarrativeError = String(err)
    } finally {
      createNarrativeBusy = false
    }
  }

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

  async function onNodeNavigate(addr: string) {
    const isCursor = $stats?.cursor === addr
    await navigate(addr)
    treeOpen.set(false)
    if (isCursor) {
      scrollContentToBottom.update((n) => n + 1)
    }
  }
</script>

<div class="sidebar" class:open={$treeOpen} data-testid="tree-browser">
  <div class="sidebar-header">
    <strong>Navigation</strong>
    <button class="sidebar-close" on:click={() => treeOpen.set(false)} aria-label="Close">
      <CloseIcon size={18} />
    </button>
  </div>
  {#if $stats}
    <div class="narrative-switcher">
      <div class="narrative-switcher-row">
        {#if $stats.narratives.length > 0}
          <select value={$stats.active_narrative} on:change={onNarrativeChange} aria-label="Active narrative">
            {#each $stats.narratives as slug (slug)}
              <option value={slug}>{slug}</option>
            {/each}
          </select>
        {:else}
          <span class="narrative-switcher-placeholder" aria-hidden="true">No narratives yet</span>
        {/if}
        <button
          type="button"
          class="narrative-switcher-add"
          on:click={openCreateNarrativeDialog}
          aria-label="Create new narrative"
          title="New narrative"
        >
          +
        </button>
      </div>
    </div>
  {/if}

  <dialog bind:this={createDialog} class="narrative-create-dialog">
    <article>
      <header>
        <p><strong>New narrative</strong></p>
      </header>
      <form
        on:submit|preventDefault={submitNewNarrative}
      >
        <label>
          Name
          <input
            type="text"
            name="narrative-slug"
            bind:value={newNarrativeSlug}
            placeholder="e.g. campaign_two"
            autocomplete="off"
            disabled={createNarrativeBusy}
            aria-invalid={createNarrativeError ? 'true' : undefined}
            aria-describedby={createNarrativeError ? 'narrative-create-err' : undefined}
          />
        </label>
        {#if createNarrativeError}
          <p id="narrative-create-err" class="narrative-create-error" role="alert">{createNarrativeError}</p>
        {/if}
        <footer>
          <button type="button" class="secondary" on:click={closeCreateNarrativeDialog} disabled={createNarrativeBusy}>
            Cancel
          </button>
          <button type="submit" disabled={createNarrativeBusy}>
            {createNarrativeBusy ? 'Creating…' : 'Create'}
          </button>
        </footer>
      </form>
    </article>
  </dialog>
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
