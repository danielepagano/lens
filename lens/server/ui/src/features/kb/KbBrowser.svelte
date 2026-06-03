<script lang="ts">
  import { get } from 'svelte/store'
  import { getKbTags, getKbItems, createKbItem } from '../../services/api'
  import type { KbItem } from '../../services/api'
  import { kbFilters, selectedKbId, treeRefreshTrigger } from '../../stores/ui'
  import type { KbFilterState } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { stats } from '../../stores/stats'
  import { currentProject } from '../../stores/project'

  type Props = {
    onSelect?: (id: string) => void
  }

  let { onSelect = undefined }: Props = $props()

  let allTags = $state.raw<string[]>([])
  let items = $state.raw<KbItem[]>([])
  let error = $state('')
  let hasSearched = $state(false)

  let tagInput = $state('')
  let showSuggestions = $state(false)

  let showNewForm = $state(false)
  let newId = $state('')
  let newUseTemplate = $state(true)
  let newError = $state('')

  let selectedType = $derived($kbFilters.type)
  let activeTags = $derived($kbFilters.tags)
  let keyFilter = $derived(selectedType && tagInput.trim() ? tagInput.trim() : '')
  let tagSuggestions = $derived.by(() => {
    const query = tagInput.trim().toLowerCase()
    if (!query) return []
    return allTags.filter(
      (tag) => tag.toLowerCase().includes(query) && !activeTags.includes(tag)
    )
  })
  let visibleItems = $derived.by(() => {
    if (!selectedType || !keyFilter) return items
    const prefix = `${selectedType}.${keyFilter}`.toLowerCase()
    return items.filter((item) => item.id.toLowerCase().startsWith(prefix))
  })

  let filterSeq = 0
  let lastRefreshTrigger = -1

  function filtersEqual(a: KbFilterState, b: KbFilterState): boolean {
    return (
      a.type === b.type &&
      a.tags.length === b.tags.length &&
      a.tags.every((tag, index) => tag === b.tags[index])
    )
  }

  function snapshotFilters(): KbFilterState {
    return { type: selectedType, tags: [...activeTags] }
  }

  function selectValue(event: Event): string {
    return (event.currentTarget as HTMLInputElement | HTMLSelectElement).value
  }

  function currentBasePath(): string {
    return [$currentProject, $currentAddress || ''].filter(Boolean).join('/')
  }

  async function loadKbFilters(filters: KbFilterState, seq: number, refreshTrigger: number) {
    try {
      allTags = await getKbTags({ type: filters.type || undefined })
    } catch (err) {
      if (seq !== filterSeq || !filtersEqual(filters, get(kbFilters))) return
      error = String(err)
    }
    if (seq !== filterSeq || !filtersEqual(filters, get(kbFilters))) return

    if (!filters.type && filters.tags.length === 0) {
      hasSearched = false
      items = []
      return
    }

    error = ''
    hasSearched = true
    lastRefreshTrigger = refreshTrigger

    try {
      const nextItems = await getKbItems({
        type: filters.type || undefined,
        tags: filters.tags.length > 0 ? filters.tags.join(',') : undefined,
      })
      if (seq !== filterSeq || !filtersEqual(filters, get(kbFilters))) return
      items = nextItems
      lastRefreshTrigger = refreshTrigger
    } catch (err) {
      if (seq !== filterSeq || !filtersEqual(filters, get(kbFilters))) return
      error = String(err)
    }
  }

  $effect(() => {
    const seq = ++filterSeq
    void loadKbFilters(snapshotFilters(), seq, get(treeRefreshTrigger))
  })

  $effect(() => {
    const refreshTrigger = $treeRefreshTrigger
    if (!hasSearched || refreshTrigger === lastRefreshTrigger) return
    lastRefreshTrigger = refreshTrigger
    const seq = ++filterSeq
    void loadKbFilters(snapshotFilters(), seq, refreshTrigger)
  })

  function handleTypeChange(event: Event) {
    kbFilters.set({ type: selectValue(event), tags: [] })
    tagInput = ''
    showSuggestions = false
  }

  function handleTagInput(event: Event) {
    tagInput = selectValue(event)
    showSuggestions = tagInput.trim().length > 0
  }

  function hideSuggestionsLater() {
    window.setTimeout(() => {
      showSuggestions = false
    }, 150)
  }

  function addTag(tag: string) {
    if (!activeTags.includes(tag)) {
      kbFilters.update((filters) => ({ ...filters, tags: [...filters.tags, tag] }))
    }
    tagInput = ''
    showSuggestions = false
  }

  function removeTag(tag: string) {
    kbFilters.update((filters) => ({
      ...filters,
      tags: filters.tags.filter((value) => value !== tag),
    }))
  }

  function handleTagInputKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && tagInput.trim()) {
      event.preventDefault()
      addTag(tagInput.trim())
    } else if (event.key === 'Escape') {
      showSuggestions = false
    }
  }

  function handleItemClick(id: string) {
    window.location.hash = `${currentBasePath()}?kb=${encodeURIComponent(id)}`
    onSelect?.(id)
  }

  function openNewForm() {
    showNewForm = true
    newError = ''
  }

  function closeNewForm() {
    showNewForm = false
    newError = ''
  }

  async function createItem() {
    const trimmedId = newId.trim()
    if (!trimmedId) {
      newError = 'ID is required'
      return
    }

    newError = ''
    try {
      const result = await createKbItem(trimmedId, undefined, newUseTemplate)
      window.location.hash = `${currentBasePath()}?kb=${encodeURIComponent(result.id)}`
      onSelect?.(result.id)
      treeRefreshTrigger.update((count) => count + 1)
      showNewForm = false
      newId = ''
      newUseTemplate = true
    } catch (err) {
      newError = String(err)
    }
  }
</script>

<div class="kb-browser">
  <div class="kb-browser-filters">
    <select value={selectedType} onchange={handleTypeChange} class="kb-type-select" aria-label="Filter by type">
      <option value="">All types</option>
      {#each $stats?.kb_types ?? [] as type (type)}
        <option value={type}>{type}</option>
      {/each}
    </select>

    <div class="kb-tag-filter">
      {#if activeTags.length > 0}
        <div class="kb-active-tags">
          {#each activeTags as tag (tag)}
            <span class="kb-tag-chip">
              {tag}
              <button class="kb-tag-remove" onclick={() => removeTag(tag)} aria-label={`Remove tag ${tag}`}>×</button>
            </span>
          {/each}
        </div>
      {/if}

      <div class="kb-tag-input-wrap">
        <input
          class="kb-tag-input"
          type="text"
          value={tagInput}
          placeholder="Filter by tag…"
          oninput={handleTagInput}
          onkeydown={handleTagInputKeydown}
          onblur={hideSuggestionsLater}
          autocomplete="off"
        />
        {#if showSuggestions && tagSuggestions.length > 0}
          <ul class="kb-tag-suggestions">
            {#each tagSuggestions.slice(0, 12) as suggestion (suggestion)}
              <li>
                <button onclick={() => addTag(suggestion)}>{suggestion}</button>
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
    {:else if visibleItems.length === 0}
      <p class="empty-state">{hasSearched ? 'No items found.' : 'Select a type or add a tag filter to search KB.'}</p>
    {:else}
      <ul class="kb-item-list">
        {#each visibleItems as item (item.id)}
          <li>
            <button class={['kb-item-btn', { active: $selectedKbId === item.id }]} onclick={() => handleItemClick(item.id)}>
              <span class="kb-item-id">
                {#if selectedType && item.id.startsWith(`${selectedType}.`)}
                  {item.id.slice(selectedType.length + 1)}
                {:else}
                  {item.id}
                {/if}
              </span>
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
        <input class="kb-new-id-input" type="text" placeholder="type.key (e.g. npc.aria)" bind:value={newId} onkeydown={(event) => event.key === 'Enter' && createItem()} />
        <label class="kb-template-label">
          <input type="checkbox" bind:checked={newUseTemplate} />
          use template
        </label>
        {#if newError}
          <p class="error-state kb-new-error">{newError}</p>
        {/if}
        <div class="kb-new-actions">
          <button class="kb-create-btn" onclick={createItem}>Create</button>
          <button class="kb-cancel-btn" onclick={closeNewForm}>Cancel</button>
        </div>
      </div>
    {:else}
      <button class="kb-add-btn" onclick={openNewForm}>+ New item</button>
    {/if}
  </div>
</div>
