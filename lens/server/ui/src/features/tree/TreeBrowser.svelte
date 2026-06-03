<script lang="ts">
  import { getTree, getStats, setActiveNarrative } from '../../services/api'
  import type { NarrativeKind, TreeNode } from '../../services/api'
  import CloseIcon from '../../components/icons/CloseIcon.svelte'
  import { currentProject, availableProjects } from '../../stores/project'
  import { applyStats, stats } from '../../stores/stats'
  import { scrollContentToBottom, treeOpen, treeRefreshTrigger } from '../../stores/ui'
  import TreeNodeComp from './TreeNode.svelte'

  type Props = { navigate: (addr: string) => Promise<void>; onProjectSwitch?: (slug: string) => Promise<void> }

  let { navigate, onProjectSwitch = undefined }: Props = $props()

  let tree = $state.raw<TreeNode[]>([])
  let error = $state('')

  let createDialog: HTMLDialogElement | undefined
  let newNarrativeSlug = $state('')
  let createNarrativeError = $state('')
  let createNarrativeBusy = $state(false)
  let narrativeKind = $state<NarrativeKind>('default')
  let companionAsKbId = $state('')
  let companionWithKbId = $state('')
  let createNarrativeBootstrapHint = $state('')

  const SLUG_RE = /^[a-zA-Z0-9_-]+$/
  const COMPANION_PREFIX = 'companion.'
  const HUMAN_PREFIX = 'human.'
  const hasCompanionDataset = $derived($stats?.current_datasets?.includes('companion') === true)
  const refreshTrigger = $derived($treeRefreshTrigger)

  function selectValue(event: Event): string {
    return (event.currentTarget as HTMLInputElement | HTMLSelectElement).value
  }

  function openCreateNarrativeDialog() {
    newNarrativeSlug = ''
    createNarrativeError = ''
    createNarrativeBootstrapHint = ''
    narrativeKind = 'default'
    companionAsKbId = COMPANION_PREFIX
    companionWithKbId = HUMAN_PREFIX
    createDialog?.showModal()
  }

  function closeCreateNarrativeDialog() {
    createNarrativeBusy = false
    createDialog?.close()
  }

  function dismissCompanionBootstrapHint() {
    createNarrativeBootstrapHint = ''
    closeCreateNarrativeDialog()
    treeOpen.set(false)
  }

  function normalizeCompanionKbId(value: string, prefix: string): string {
    return narrativeKind === 'companion_chat' && value.trim() === '' ? prefix : value
  }

  function ensureCompanionDefaults() {
    companionAsKbId = normalizeCompanionKbId(companionAsKbId, COMPANION_PREFIX)
    companionWithKbId = normalizeCompanionKbId(companionWithKbId, HUMAN_PREFIX)
  }

  function kbPrefixFilled(prefix: string, value: string): boolean {
    const trimmed = value.trim()
    return trimmed.length > prefix.length && trimmed.toLowerCase().startsWith(prefix.toLowerCase())
  }

  async function refreshNarrativeState() {
    treeRefreshTrigger.update((count) => count + 1)
    tree = await getTree()
    const newStats = await getStats()
    applyStats(newStats)
    if (newStats.cursor) await navigate(newStats.cursor)
  }

  function handleProjectChange(event: Event) {
    const slug = selectValue(event)
    if (slug && slug !== $currentProject) void onProjectSwitch?.(slug)
  }

  function handleNarrativeKindChange() {
    ensureCompanionDefaults()
  }

  function handleCompanionAsKbIdInput(event: Event) {
    companionAsKbId = normalizeCompanionKbId(selectValue(event), COMPANION_PREFIX)
  }

  function handleCompanionWithKbIdInput(event: Event) {
    companionWithKbId = normalizeCompanionKbId(selectValue(event), HUMAN_PREFIX)
  }

  async function handleCreateNarrativeSubmit(event: SubmitEvent) {
    event.preventDefault()
    await submitNewNarrative()
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
    if (narrativeKind === 'companion_chat') {
      const companionAs = companionAsKbId.trim()
      const companionWith = companionWithKbId.trim()
      if (!kbPrefixFilled(COMPANION_PREFIX, companionAs) || !kbPrefixFilled(HUMAN_PREFIX, companionWith)) {
        createNarrativeError =
          'Enter full KB ids, e.g. companion.mara and human.adam (prefixes may be edited).'
        return
      }
    }
    createNarrativeError = ''
    createNarrativeBusy = true
    try {
      const options =
        narrativeKind === 'companion_chat'
          ? {
              narrativeKind: 'companion_chat' as const,
              companionAsKbId: companionAsKbId.trim(),
              companionWithKbId: companionWithKbId.trim(),
            }
          : undefined
      const result = await setActiveNarrative(slug, options)
      await refreshNarrativeState()
      if (result.companion_bootstrap) {
        createNarrativeBootstrapHint = result.companion_bootstrap
        return
      }
      closeCreateNarrativeDialog()
      treeOpen.set(false)
    } catch (err) {
      createNarrativeError = String(err)
    } finally {
      createNarrativeBusy = false
    }
  }

  async function handleNarrativeChange(event: Event) {
    const slug = selectValue(event)
    try {
      await setActiveNarrative(slug)
      await refreshNarrativeState()
      treeOpen.set(false)
    } catch (err) {
      error = String(err)
    }
  }

  async function handleNodeNavigate(addr: string) {
    const isCursor = $stats?.cursor === addr
    await navigate(addr)
    treeOpen.set(false)
    if (isCursor) scrollContentToBottom.update((count) => count + 1)
  }

  $effect(() => {
    void refreshTrigger
    void getTree()
      .then((nextTree) => {
        tree = nextTree
      })
      .catch((err) => {
        error = String(err)
      })
  })
</script>

<div class={['sidebar', { open: $treeOpen }]} data-testid="tree-browser">
  <div class="sidebar-header">
    {#if $availableProjects.length > 1}
      <select class="project-select" value={$currentProject ?? ''} onchange={handleProjectChange} aria-label="Select project">
        {#each $availableProjects as slug (slug)}
          <option value={slug}>{slug}</option>
        {/each}
      </select>
    {:else}
      <strong>Navigation</strong>
    {/if}
    <button class="sidebar-close" onclick={() => treeOpen.set(false)} aria-label="Close">
      <CloseIcon size={18} />
    </button>
  </div>
  {#if $stats}
    <div class="narrative-switcher">
      <div class="narrative-switcher-row">
        {#if $stats.narratives.length > 0}
          <select value={$stats.active_narrative} onchange={handleNarrativeChange} aria-label="Active narrative">
            {#each $stats.narratives as slug (slug)}
              <option value={slug}>{slug}</option>
            {/each}
          </select>
        {:else}
          <span class="narrative-switcher-placeholder" aria-hidden="true">No narratives yet</span>
        {/if}
        <button type="button" class="narrative-switcher-add" onclick={openCreateNarrativeDialog} aria-label="Create new narrative" title="New narrative">+</button>
      </div>
    </div>
  {/if}

  <dialog bind:this={createDialog} class="narrative-create-dialog">
    <article>
      <header>
        <p><strong>New narrative</strong></p>
      </header>
      {#if createNarrativeBootstrapHint}
        <p class="narrative-create-hint" role="status">{createNarrativeBootstrapHint}</p>
        <footer>
          <button type="button" class="secondary" onclick={dismissCompanionBootstrapHint}>
            Close
          </button>
        </footer>
      {:else}
        <form onsubmit={handleCreateNarrativeSubmit}>
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
          {#if hasCompanionDataset}
            <fieldset class="narrative-create-type" disabled={createNarrativeBusy}>
              <legend>Type</legend>
              <label>
                <input type="radio" bind:group={narrativeKind} value="default" onchange={handleNarrativeKindChange} />
                Standard
              </label>
              <label>
                <input type="radio" bind:group={narrativeKind} value="companion_chat" onchange={handleNarrativeKindChange} />
                Companion chat
              </label>
            </fieldset>
          {/if}
          {#if hasCompanionDataset && narrativeKind === 'companion_chat'}
            <label>
              Companion KB id
              <input type="text" name="companion-as-kb" value={companionAsKbId} oninput={handleCompanionAsKbIdInput} placeholder="companion.mara" autocomplete="off" disabled={createNarrativeBusy} />
            </label>
            <label>
              Human KB id
              <input type="text" name="companion-with-kb" value={companionWithKbId} oninput={handleCompanionWithKbIdInput} placeholder="human.adam" autocomplete="off" disabled={createNarrativeBusy} />
            </label>
          {/if}
          {#if createNarrativeError}
            <p id="narrative-create-err" class="narrative-create-error" role="alert">{createNarrativeError}</p>
          {/if}
          <footer>
            <button type="button" class="secondary" onclick={closeCreateNarrativeDialog} disabled={createNarrativeBusy}>Cancel</button>
            <button type="submit" disabled={createNarrativeBusy}>
              {createNarrativeBusy ? 'Creating…' : 'Create'}
            </button>
          </footer>
        </form>
      {/if}
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
          <TreeNodeComp node={node} isRoot={i === 0} onNavigate={handleNodeNavigate} />
        {/each}
      </ul>
    {/if}
  </div>
</div>
