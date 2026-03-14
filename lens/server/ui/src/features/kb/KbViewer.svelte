<script lang="ts">
  import { selectedKbId, treeRefreshTrigger } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { getKbItem, saveKbItem, getKbWithTag } from '../../services/api'
  import type { KbItemDetail } from '../../services/api'
  import { createMarkdownRenderer } from '../../utils/markdown'

  const md = createMarkdownRenderer()

  let item: KbItemDetail | null = null
  let editMode = false
  let editContent = ''
  let saving = false
  let saveError = ''
  let loadError = ''
  let linkedFrom: string[] = []

  async function loadItem(id: string) {
    loadError = ''
    saveError = ''
    editMode = false
    linkedFrom = []
    try {
      item = await getKbItem(id)
      editContent = item.content
      const linked = await getKbWithTag([id])
      linkedFrom = linked.ids
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

  function isDotTag(tag: string): boolean {
    return tag.includes('.')
  }

  function openKbItem(id: string) {
    const path = $currentAddress || ''
    window.location.hash = `${path}?kb=${encodeURIComponent(id)}`
  }
</script>

<div class="kb-viewer">
  {#if loadError}
    <p class="error-state">{loadError}</p>
  {:else if !item}
    <p class="empty-state">No KB item selected.</p>
  {:else}
    <div class="kb-viewer-header">
      <span class="kb-viewer-id">{item.id}</span>
      {#if item.tags.length > 0}
        <span class="kb-viewer-tags">
          {#each item.tags as tag, i (tag)}
            {#if i > 0}<span class="kb-viewer-tag-sep"> · </span>{/if}
            {#if isDotTag(tag)}
              <a class="kb-viewer-tag kb-viewer-tag-link" href="#{tag}" on:click|preventDefault={() => openKbItem(tag)}>{tag}</a>
            {:else}
              <span class="kb-viewer-tag">{tag}</span>
            {/if}
          {/each}
        </span>
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
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
        {@html rendered}
      </article>
    {/if}

    {#if linkedFrom.length > 0}
      <div class="kb-linked-from">
        <span class="kb-linked-from-label">Linked from:</span>
        {#each linkedFrom as linkedId, i (linkedId)}
          {#if i > 0}<span class="kb-linked-from-sep">, </span>{/if}
          <a class="kb-linked-from-link" href="#{linkedId}" on:click|preventDefault={() => openKbItem(linkedId)}>{linkedId}</a>
        {/each}
      </div>
    {/if}
  {/if}
</div>
