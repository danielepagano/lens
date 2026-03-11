<script lang="ts">
  import { onMount } from 'svelte'
  import { getKbTypes, getKbTags, getKbItems, createKbItem } from '../../services/api'
  import type { KbItem } from '../../services/api'
  import { kbFilters, selectedKbId } from '../../stores/ui'

  let types: string[] = []
  let allTags: string[] = []
  let items: KbItem[] = []
  let error = ''
  let hasSearched = false

  let selectedType = ''
  let tagInput = ''
  let tagSuggestions: string[] = []
  let activeTags: string[] = []
  let showSuggestions = false

  export let onSelect: ((id: string) => void) | undefined = undefined

  let didInitFromStore = false

  $: if (!didInitFromStore) {
    selectedType = $kbFilters.type
    activeTags = $kbFilters.tags
    didInitFromStore = true
  }

  $: if (didInitFromStore) {
    const next = { type: selectedType, tags: activeTags }
    const prev = $kbFilters
    const same =
      prev.type === next.type &&
      prev.tags.length === next.tags.length &&
      prev.tags.every((t, i) => t === next.tags[i])
    if (!same) kbFilters.set(next)
  }

  async function loadTypes() {
    try {
      types = await getKbTypes()
    } catch (e) {
      error = String(e)
    }
  }

  async function loadTags() {
    try {
      allTags = await getKbTags({ type: selectedType || undefined })
    } catch (e) {
      error = String(e)
    }
  }

  async function loadItems() {
    try {
      error = ''
      hasSearched = true
      items = await getKbItems({
        type: selectedType || undefined,
        tags: activeTags.length ? activeTags.join(',') : undefined,
      })
    } catch (e) {
      error = String(e)
    }
  }

  onMount(async () => {
    await loadTypes()
    await loadTags()
    if (selectedType || activeTags.length > 0) {
      await loadItems()
    }
  })

  async function onTypeChange() {
    activeTags = []
    tagInput = ''
    await loadTags()
    await loadItems()
  }

  function onTagInputInput(e: Event) {
    const val = (e.target as HTMLInputElement).value
    tagInput = val
    if (val.trim()) {
      tagSuggestions = allTags.filter(
        (t) => t.toLowerCase().includes(val.toLowerCase()) && !activeTags.includes(t)
      )
      showSuggestions = tagSuggestions.length > 0
    } else {
      tagSuggestions = []
      showSuggestions = false
    }
  }

  async function addTag(tag: string) {
    if (!activeTags.includes(tag)) {
      activeTags = [...activeTags, tag]
      await loadItems()
    }
    tagInput = ''
    tagSuggestions = []
    showSuggestions = false
  }

  async function removeTag(tag: string) {
    activeTags = activeTags.filter((t) => t !== tag)
    await loadItems()
  }

  async function onTagInputKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && tagInput.trim()) {
      e.preventDefault()
      await addTag(tagInput.trim())
    } else if (e.key === 'Escape') {
      showSuggestions = false
    }
  }

  function onItemClick(id: string) {
    selectedKbId.set(id)
    if (onSelect) onSelect(id)
  }

  // New item form state
  let showNewForm = false
  let newId = ''
  let newUseTemplate = true
  let newError = ''

  async function createItem() {
    if (!newId.trim()) {
      newError = 'ID is required'
      return
    }
    newError = ''
    try {
      const result = await createKbItem(newId.trim(), undefined, newUseTemplate)
      selectedKbId.set(result.id)
      if (onSelect) onSelect(result.id)
      // Refresh list after selection so the viewer opens immediately.
      await loadItems()
      showNewForm = false
      newId = ''
      newUseTemplate = true
    } catch (e) {
      newError = String(e)
    }
  }
</script>

<div class="kb-browser">
  <div class="kb-browser-filters">
    <select
      bind:value={selectedType}
      on:change={onTypeChange}
      class="kb-type-select"
      aria-label="Filter by type"
    >
      <option value="">All types</option>
      {#each types as t (t)}
        <option value={t}>{t}</option>
      {/each}
    </select>

    <div class="kb-tag-filter">
      {#if activeTags.length > 0}
        <div class="kb-active-tags">
          {#each activeTags as tag (tag)}
            <span class="kb-tag-chip">
              {tag}
              <button
                class="kb-tag-remove"
                on:click={() => removeTag(tag)}
                aria-label="Remove tag {tag}"
              >×</button>
            </span>
          {/each}
        </div>
      {/if}
      <div class="kb-tag-input-wrap">
        <input
          class="kb-tag-input"
          type="text"
          placeholder="Filter by tag…"
          bind:value={tagInput}
          on:input={onTagInputInput}
          on:keydown={onTagInputKeydown}
          on:blur={() => setTimeout(() => { showSuggestions = false }, 150)}
          autocomplete="off"
        />
        {#if showSuggestions}
          <ul class="kb-tag-suggestions">
            {#each tagSuggestions.slice(0, 12) as sug (sug)}
              <li>
                <button on:click={() => addTag(sug)}>{sug}</button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    </div>
  </div>

  <div class="kb-browser-list">
    {#if error}
      <p class="error-state">{error}</p>
    {:else if items.length === 0}
      {#if hasSearched}
        <p class="empty-state">No items found.</p>
      {:else}
        <p class="empty-state">Select a type or add a tag filter to search KB.</p>
      {/if}
    {:else}
      <ul class="kb-item-list">
        {#each items as item (item.id)}
          <li>
            <button
              class="kb-item-btn"
              class:active={$selectedKbId === item.id}
              on:click={() => onItemClick(item.id)}
            >
              <span class="kb-item-id">{item.id}</span>
              {#if item.tags.length > 0}
                <span class="kb-item-tags">{item.tags.join(' · ')}</span>
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="kb-browser-footer">
    {#if showNewForm}
      <div class="kb-new-form">
        <input
          class="kb-new-id-input"
          type="text"
          placeholder="type.key (e.g. npc.aria)"
          bind:value={newId}
          on:keydown={(e) => e.key === 'Enter' && createItem()}
        />
        <label class="kb-template-label">
          <input type="checkbox" bind:checked={newUseTemplate} />
          use template
        </label>
        {#if newError}
          <p class="error-state kb-new-error">{newError}</p>
        {/if}
        <div class="kb-new-actions">
          <button class="kb-create-btn" on:click={createItem}>Create</button>
          <button class="kb-cancel-btn" on:click={() => { showNewForm = false; newError = '' }}>Cancel</button>
        </div>
      </div>
    {:else}
      <button class="kb-add-btn" on:click={() => { showNewForm = true }}>+ New item</button>
    {/if}
  </div>
</div>
