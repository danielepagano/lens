<script lang="ts">
  import { onMount } from 'svelte'
  import { selectedKbId, treeRefreshTrigger } from '../../stores/ui'
  import { getKbItem, saveKbItem } from '../../services/api'
  import type { KbItemDetail } from '../../services/api'
  import { createMarkdownRenderer } from '../../utils/markdown'

  const md = createMarkdownRenderer()

  let item: KbItemDetail | null = null
  let editMode = false
  let editContent = ''
  let saving = false
  let saveError = ''
  let loadError = ''

  async function loadItem(id: string) {
    loadError = ''
    saveError = ''
    editMode = false
    try {
      item = await getKbItem(id)
      editContent = item.content
    } catch (e) {
      loadError = String(e)
      item = null
    }
  }

  $: if ($selectedKbId) {
    void loadItem($selectedKbId)
  } else {
    item = null
    loadError = ''
  }

  function enterEdit() {
    if (item) {
      editContent = item.content
      editMode = true
      saveError = ''
    }
  }

  function cancelEdit() {
    editMode = false
    saveError = ''
  }

  async function save() {
    if (!item) return
    saving = true
    saveError = ''
    try {
      await saveKbItem(item.id, editContent)
      item = { ...item, content: editContent }
      editMode = false
      treeRefreshTrigger.update((n) => n + 1)
    } catch (e) {
      saveError = String(e)
    } finally {
      saving = false
    }
  }

  $: rendered = item ? md.render(item.content) : ''
</script>

<div class="kb-viewer">
  {#if loadError}
    <p class="error-state">{loadError}</p>
  {:else if !item}
    <p class="empty-state">Select a KB item from the list.</p>
  {:else}
    <div class="kb-viewer-header">
      <span class="kb-viewer-id">{item.id}</span>
      {#if item.tags.length > 0}
        <span class="kb-viewer-tags">{item.tags.join(' · ')}</span>
      {/if}
      <div class="kb-viewer-actions">
        {#if editMode}
          <button class="kb-save-btn" on:click={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button class="kb-cancel-edit-btn" on:click={cancelEdit} disabled={saving}>Cancel</button>
        {:else}
          <button class="kb-edit-btn" on:click={enterEdit}>Edit</button>
        {/if}
      </div>
    </div>

    {#if saveError}
      <p class="error-state kb-save-error">{saveError}</p>
    {/if}

    {#if editMode}
      <textarea
        class="kb-edit-textarea"
        bind:value={editContent}
        spellcheck="false"
        disabled={saving}
      ></textarea>
    {:else}
      <article class="content kb-rendered">
        {@html rendered}
      </article>
    {/if}
  {/if}
</div>
