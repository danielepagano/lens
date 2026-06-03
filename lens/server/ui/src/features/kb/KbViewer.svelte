<script lang="ts">
  import { onMount } from 'svelte'
  import type { Attachment } from 'svelte/attachments'
  import { selectedKbId, treeRefreshTrigger } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { currentProject } from '../../stores/project'
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
    prefixMountUrlsInRenderedHtml,
  } from '../../utils/markdown'
  import CodeMirrorEditor from '../editor/CodeMirrorEditor.svelte'

  const md = createMarkdownRenderer({ openLinksInNewTab: true })

  let item = $state.raw<KbItemDetail | null>(null)
  let editMode = $state(false)
  let editContent = $state('')
  let saving = $state(false)
  let saveError = $state('')
  let loadError = $state('')
  let linkedFrom = $state.raw<string[]>([])
  let tagsEditMode = $state(false)
  let tagInput = $state('')
  let actionsOpen = $state(false)
  let deleteConfirm = $state(false)
  let showRenameInput = $state(false)
  let showCopyInput = $state(false)
  let renameId = $state('')
  let copyTargetId = $state('')
  let actionError = $state('')
  let metaOpen = $state(false)

  const viewerHashBase = $derived([$currentProject, $currentAddress || ''].filter(Boolean).join('/'))
  const rawKbRendered = $derived(
    item
      ? md.render(
          preprocessKbReferencePills(
            preprocessBlockquotePills(item.content),
            $stats?.remember_pins_at_cursor ?? undefined,
          ),
        )
      : ''
  )
  const rendered = $derived(prefixMountUrlsInRenderedHtml(rawKbRendered, $currentProject))
  const metaSummary = $derived.by(() => {
    if (!item) return ''
    const parts: string[] = []
    parts.push(
      item.tags.length > 0
        ? `${item.tags.length} tag${item.tags.length === 1 ? '' : 's'}`
        : 'No tags',
    )
    if (linkedFrom.length > 0) {
      parts.push(`linked from ${linkedFrom.length} ${linkedFrom.length === 1 ? 'item' : 'items'}`)
    }
    return parts.join(' · ')
  })

  let activeLoadSeq = 0

  async function loadItem(id: string, loadSeq: number) {
    loadError = ''
    saveError = ''
    actionError = ''
    editMode = false
    tagsEditMode = false
    metaOpen = false
    linkedFrom = []
    try {
      const nextItem = await getKbItem(id)
      if (loadSeq !== activeLoadSeq) return
      item = nextItem
      editContent = item.content
      const linked = await getKbWithTag([id])
      if (loadSeq !== activeLoadSeq) return
      linkedFrom = linked.ids
    } catch (e) {
      if (loadSeq !== activeLoadSeq) return
      loadError = String(e)
      item = null
    }
  }

  onMount(() => {
    return selectedKbId.subscribe((id) => {
      activeLoadSeq += 1
      const loadSeq = activeLoadSeq
      if (!id) {
        item = null
        loadError = ''
        linkedFrom = []
        return
      }
      void loadItem(id, loadSeq)
    })
  })

  function toggleActionsMenu() {
    actionsOpen = !actionsOpen
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
      window.location.hash = viewerHashBase
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
      window.location.hash = `${viewerHashBase}?kb=${encodeURIComponent(newId)}`
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
      window.location.hash = `${viewerHashBase}?kb=${encodeURIComponent(targetId)}`
      treeRefreshTrigger.update((n) => n + 1)
      closeActions()
    } catch (e) {
      actionError = String(e)
    }
  }

  function isDotTag(tag: string): boolean {
    return tag.includes('.')
  }

  function openKbItem(id: string) {
    window.location.hash = `${viewerHashBase}?kb=${encodeURIComponent(id)}`
  }

  function handleKbMarkdownClick(e: MouseEvent) {
    const pinEl = (e.target as HTMLElement).closest('[data-kb-open-id]')
    if (!pinEl) return
    const id = pinEl.getAttribute('data-kb-open-id')
    if (id) openKbItem(id)
  }

  const attachKbMarkdownClicks: Attachment<HTMLDivElement> = (element) => {
    const handleClick = (event: MouseEvent) => handleKbMarkdownClick(event)
    element.addEventListener('click', handleClick)
    return () => {
      element.removeEventListener('click', handleClick)
    }
  }

  function handleActionInputKeydown(event: KeyboardEvent, action: () => void) {
    if (event.key === 'Enter') {
      action()
    }
  }

  function cancelRename() {
    showRenameInput = false
    renameId = ''
  }

  function cancelCopy() {
    showCopyInput = false
    copyTargetId = ''
  }

  function startDeleteConfirm() {
    deleteConfirm = true
  }

  function startRename() {
    showRenameInput = true
    renameId = item ? `${item.type}.` : ''
  }

  function startCopy() {
    showCopyInput = true
    copyTargetId = item ? `${item.type}.` : ''
  }

  function stopTagsEdit() {
    tagsEditMode = false
  }

  function openKbItemFromClick(event: MouseEvent, id: string) {
    event.preventDefault()
    openKbItem(id)
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
      <div class="kb-viewer-actions">
        <div class="kb-viewer-action-strip">
          {#if editMode}
            <button type="button" class="kb-action-btn kb-action-btn-primary" onclick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" class="kb-action-btn" onclick={cancelEdit} disabled={saving}>Cancel</button>
          {:else}
            <button type="button" class="kb-action-btn" onclick={enterEdit}>Edit</button>
            <div class="kb-viewer-menu-wrap">
              <button
                type="button"
                class="kb-action-btn kb-action-btn-icon"
                aria-haspopup="true"
                aria-expanded={actionsOpen}
                onclick={toggleActionsMenu}
              >…</button>
              {#if actionsOpen}
                <div class="kb-viewer-menu" role="menu">
                  {#if deleteConfirm}
                    <div class="kb-menu-delete-confirm">
                      <span>Delete this item?</span>
                      <button type="button" class="kb-menu-confirm-btn" onclick={doDelete}>Delete</button>
                      <button type="button" onclick={() => (deleteConfirm = false)}>Cancel</button>
                    </div>
                  {:else if showRenameInput}
                    <div class="kb-menu-rename">
                      <input
                        type="text"
                        placeholder="New ID"
                        bind:value={renameId}
                        onkeydown={(event) => handleActionInputKeydown(event, doRename)}
                      />
                      <button type="button" onclick={doRename}>Rename</button>
                      <button type="button" onclick={cancelRename}>Cancel</button>
                    </div>
                  {:else if showCopyInput}
                    <div class="kb-menu-copy">
                      <input
                        type="text"
                        placeholder="Target ID"
                        bind:value={copyTargetId}
                        onkeydown={(event) => handleActionInputKeydown(event, doCopy)}
                      />
                      <button type="button" onclick={doCopy}>Copy</button>
                      <button type="button" onclick={cancelCopy}>Cancel</button>
                    </div>
                  {:else}
                    <button type="button" role="menuitem" onclick={startDeleteConfirm}>Delete</button>
                    <button type="button" role="menuitem" onclick={startRename}>Rename</button>
                    <button type="button" role="menuitem" onclick={startCopy}>Copy</button>
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
        onChange={(text) => {
          editContent = text
        }}
      />
    {:else}
      <article class="content kb-rendered">
        <div class="kb-rendered-md" {@attach attachKbMarkdownClicks}>
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
                <button type="button" class="kb-tag-delete-pill" onclick={() => removeTag(tag)} title="Remove tag">{tag} ×</button>
              {/each}
            </div>
            <div class="kb-tags-edit-input-row">
              <input
                type="text"
                class="kb-viewer-tag-input"
                placeholder="Add tag…"
                bind:value={tagInput}
                onkeydown={(event) => handleActionInputKeydown(event, addTagFromInput)}
                onblur={addTagFromInput}
              />
              <button type="button" class="kb-meta-small-btn" onclick={stopTagsEdit}>Done</button>
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
                      <a class="kb-viewer-tag kb-viewer-tag-link" href="#{tag}" onclick={(event) => openKbItemFromClick(event, tag)}>{tag}</a>
                    {:else}
                      <span class="kb-viewer-tag">{tag}</span>
                    {/if}
                  {/each}
                {:else}
                  No tags
                {/if}
              </span>
              <button type="button" class="kb-meta-small-btn" onclick={enterTagsEdit}>Edit tags</button>
            </div>
            {#if linkedFrom.length > 0}
              <div class="kb-meta-linked-row">
                <span class="kb-linked-from-label">Linked from:</span>
                {#each linkedFrom as linkedId, i (linkedId)}
                  {#if i > 0}<span class="kb-linked-from-sep">, </span>{/if}
                  <a class="kb-linked-from-link" href="#{linkedId}" onclick={(event) => openKbItemFromClick(event, linkedId)}>{linkedId}</a>
                {/each}
              </div>
            {/if}
          {/if}
        </div>
      </details>
    {/if}
  {/if}
</div>
