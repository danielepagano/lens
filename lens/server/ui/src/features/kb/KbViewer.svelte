<script lang="ts">
  import { selectedKbId, treeRefreshTrigger } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { stats } from '../../stores/stats'
  import {
    getKbItem,
    saveKbItem,
    getKbWithTag,
    patchKbItemTags,
    deleteKbItem,
    renameKbItem,
    copyKbItem,
  } from '../../services/api'
  import type { KbItemDetail } from '../../services/api'
  import {
    createMarkdownRenderer,
    preprocessBlockquotePills,
    preprocessKbReferencePills,
  } from '../../utils/markdown'
  import CodeMirrorEditor from '../editor/CodeMirrorEditor.svelte'

  const md = createMarkdownRenderer()

  let item: KbItemDetail | null = null
  let editMode = false
  let editContent = ''
  let saving = false
  let saveError = ''
  let loadError = ''
  let linkedFrom: string[] = []
  let tagsEditMode = false
  let tagInput = ''
  let actionsOpen = false
  let deleteConfirm = false
  let showRenameInput = false
  let showCopyInput = false
  let renameId = ''
  let copyTargetId = ''
  let actionError = ''
  let metaOpen = false

  async function loadItem(id: string) {
    loadError = ''
    saveError = ''
    actionError = ''
    editMode = false
    tagsEditMode = false
    metaOpen = false
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
      tagsEditMode = false
      editMode = true
      saveError = ''
      actionsOpen = false
    }
  }

  function cancelEdit() {
    editMode = false
    saveError = ''
  }

  function enterTagsEdit() {
    editMode = false
    saveError = ''
    tagsEditMode = true
    metaOpen = true
    actionsOpen = false
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

  async function removeTag(tag: string) {
    if (!item) return
    actionError = ''
    try {
      const res = await patchKbItemTags(item.id, { add: [], remove: [tag] })
      item = { ...item, tags: res.tags }
    } catch (e) {
      actionError = String(e)
    }
  }

  async function addTagFromInput() {
    const val = tagInput.trim()
    if (!item || !val) return
    if (item.tags.includes(val)) {
      tagInput = ''
      return
    }
    actionError = ''
    try {
      const res = await patchKbItemTags(item.id, { add: [val], remove: [] })
      item = { ...item, tags: res.tags }
      tagInput = ''
    } catch (e) {
      actionError = String(e)
    }
  }

  function closeActions() {
    actionsOpen = false
    deleteConfirm = false
    showRenameInput = false
    showCopyInput = false
    renameId = ''
    copyTargetId = ''
    actionError = ''
  }

  async function doDelete() {
    if (!item) return
    try {
      await deleteKbItem(item.id)
      selectedKbId.set(null)
      window.location.hash = $currentAddress || ''
      treeRefreshTrigger.update((n) => n + 1)
      closeActions()
    } catch (e) {
      actionError = String(e)
    }
  }

  async function doRename() {
    if (!item) return
    const newId = renameId.trim()
    if (!newId || newId === item.id) {
      if (!newId) closeActions()
      return
    }
    try {
      await renameKbItem(item.id, newId)
      selectedKbId.set(newId)
      const path = $currentAddress || ''
      window.location.hash = `${path}?kb=${encodeURIComponent(newId)}`
      treeRefreshTrigger.update((n) => n + 1)
      closeActions()
    } catch (e) {
      actionError = String(e)
    }
  }

  async function doCopy() {
    if (!item || !copyTargetId.trim()) return
    const targetId = copyTargetId.trim()
    try {
      await copyKbItem(item.id, targetId)
      selectedKbId.set(targetId)
      const path = $currentAddress || ''
      window.location.hash = `${path}?kb=${encodeURIComponent(targetId)}`
      treeRefreshTrigger.update((n) => n + 1)
      closeActions()
    } catch (e) {
      actionError = String(e)
    }
  }

  $: rendered = item
    ? md.render(
        preprocessKbReferencePills(
          preprocessBlockquotePills(item.content),
          $stats?.remember_pins_at_cursor ?? undefined,
        ),
      )
    : ''

  function isDotTag(tag: string): boolean {
    return tag.includes('.')
  }

  function openKbItem(id: string) {
    const path = $currentAddress || ''
    window.location.hash = `${path}?kb=${encodeURIComponent(id)}`
  }

  function handleKbMarkdownClick(e: MouseEvent) {
    const pinEl = (e.target as HTMLElement).closest('[data-kb-open-id]')
    if (!pinEl) return
    const id = pinEl.getAttribute('data-kb-open-id')
    if (id) openKbItem(id)
  }

  $: metaSummary = (() => {
    if (!item) return ''
    const parts: string[] = []
    parts.push(
      item.tags.length > 0
        ? `${item.tags.length} tag${item.tags.length === 1 ? '' : 's'}`
        : 'No tags',
    )
    if (linkedFrom.length > 0) parts.push(`linked from ${linkedFrom.length} ${linkedFrom.length === 1 ? 'item' : 'items'}`)
    return parts.join(' · ')
  })()
</script>

<div class="kb-viewer">
  {#if loadError}
    <p class="error-state">{loadError}</p>
  {:else if !item}
    <p class="empty-state">No KB item selected.</p>
  {:else}
    <div class="kb-viewer-header">
      <span class="kb-viewer-id">{item.id}</span>
      <div class="kb-viewer-actions">
        <div class="kb-viewer-action-strip">
          {#if editMode}
            <button type="button" class="kb-action-btn kb-action-btn-primary" on:click={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" class="kb-action-btn" on:click={cancelEdit} disabled={saving}>Cancel</button>
          {:else}
            <button type="button" class="kb-action-btn" on:click={enterEdit}>Edit</button>
            <div class="kb-viewer-menu-wrap">
              <button
                type="button"
                class="kb-action-btn kb-action-btn-icon"
                aria-haspopup="true"
                aria-expanded={actionsOpen}
                on:click={() => (actionsOpen = !actionsOpen)}
              >…</button>
              {#if actionsOpen}
                <div class="kb-viewer-menu" role="menu">
                  {#if deleteConfirm}
                    <div class="kb-menu-delete-confirm">
                      <span>Delete this item?</span>
                      <button type="button" class="kb-menu-confirm-btn" on:click={doDelete}>Delete</button>
                      <button type="button" on:click={() => (deleteConfirm = false)}>Cancel</button>
                    </div>
                  {:else if showRenameInput}
                    <div class="kb-menu-rename">
                      <input type="text" placeholder="New ID" bind:value={renameId} on:keydown={(e) => e.key === 'Enter' && doRename()} />
                      <button type="button" on:click={doRename}>Rename</button>
                      <button type="button" on:click={() => { showRenameInput = false; renameId = '' }}>Cancel</button>
                    </div>
                  {:else if showCopyInput}
                    <div class="kb-menu-copy">
                      <input type="text" placeholder="Target ID" bind:value={copyTargetId} on:keydown={(e) => e.key === 'Enter' && doCopy()} />
                      <button type="button" on:click={doCopy}>Copy</button>
                      <button type="button" on:click={() => { showCopyInput = false; copyTargetId = '' }}>Cancel</button>
                    </div>
                  {:else}
                    <button type="button" role="menuitem" on:click={() => (deleteConfirm = true)}>Delete</button>
                    <button type="button" role="menuitem" on:click={() => { showRenameInput = true; renameId = item ? `${item.type}.` : '' }}>Rename</button>
                    <button type="button" role="menuitem" on:click={() => { showCopyInput = true; copyTargetId = item ? `${item.type}.` : '' }}>Copy</button>
                  {/if}
                  {#if actionError}
                    <p class="kb-menu-error">{actionError}</p>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    </div>

    {#if saveError}
      <p class="error-state kb-save-error">{saveError}</p>
    {/if}

    {#if editMode}
      <CodeMirrorEditor
        content={editContent}
        editableRange={null}
        lang="markdown"
        on:change={(e) => { editContent = e.detail }}
      />
    {:else}
      <article class="content kb-rendered">
        <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
        <div class="kb-rendered-md" on:click={handleKbMarkdownClick}>
          <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
          {@html rendered}
        </div>
      </article>
    {/if}

    {#if !editMode}
      <details class="kb-meta-section" bind:open={metaOpen}>
        <summary class="kb-meta-summary">{metaSummary}</summary>
        <div class="kb-meta-body">
          {#if tagsEditMode}
            <div class="kb-tags-edit-area">
              {#each item.tags as tag (tag)}
                <button type="button" class="kb-tag-delete-pill" on:click={() => removeTag(tag)} title="Remove tag">{tag} ×</button>
              {/each}
            </div>
            <div class="kb-tags-edit-input-row">
              <input
                type="text"
                class="kb-viewer-tag-input"
                placeholder="Add tag…"
                bind:value={tagInput}
                on:keydown={(e) => e.key === 'Enter' && addTagFromInput()}
                on:blur={() => addTagFromInput()}
              />
              <button type="button" class="kb-meta-small-btn" on:click={() => (tagsEditMode = false)}>Done</button>
            </div>
            {#if actionError}
              <p class="error-state kb-save-error">{actionError}</p>
            {/if}
          {:else}
            <div class="kb-meta-tags-row">
              <span class="kb-meta-tags-list">
                {#if item.tags.length > 0}
                  {#each item.tags as tag, i (tag)}
                    {#if i > 0}<span class="kb-viewer-tag-sep"> · </span>{/if}
                    {#if isDotTag(tag)}
                      <a class="kb-viewer-tag kb-viewer-tag-link" href="#{tag}" on:click|preventDefault={() => openKbItem(tag)}>{tag}</a>
                    {:else}
                      <span class="kb-viewer-tag">{tag}</span>
                    {/if}
                  {/each}
                {:else}
                  No tags
                {/if}
              </span>
              <button type="button" class="kb-meta-small-btn" on:click={enterTagsEdit}>Edit tags</button>
            </div>
            {#if linkedFrom.length > 0}
              <div class="kb-meta-linked-row">
                <span class="kb-linked-from-label">Linked from:</span>
                {#each linkedFrom as linkedId, i (linkedId)}
                  {#if i > 0}<span class="kb-linked-from-sep">, </span>{/if}
                  <a class="kb-linked-from-link" href="#{linkedId}" on:click|preventDefault={() => openKbItem(linkedId)}>{linkedId}</a>
                {/each}
              </div>
            {/if}
          {/if}
        </div>
      </details>
    {/if}
  {/if}
</div>
