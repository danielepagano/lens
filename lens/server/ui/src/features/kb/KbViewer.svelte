<script lang="ts">
  import { onMount } from 'svelte'
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
  import CodeMirrorEditor from '../editor/CodeMirrorEditor.svelte'
  import {
    attachKbMarkdownClicks,
    kbViewerHashBase,
    openKbItemInHash,
    renderKbMarkdown,
  } from './kbViewerMarkdown'
  import KbViewerActionsMenu from './KbViewerActionsMenu.svelte'
  import KbViewerMetaSection from './KbViewerMetaSection.svelte'

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

  const viewerHashBase = $derived(kbViewerHashBase($currentProject, $currentAddress || ''))
  const rendered = $derived(
    item
      ? renderKbMarkdown(item.content, $stats?.remember_pins_at_cursor ?? undefined, $currentProject)
      : '',
  )
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
  const markdownClickAttach = $derived(attachKbMarkdownClicks(viewerHashBase))

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
      openKbItemInHash(viewerHashBase, newId)
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
      openKbItemInHash(viewerHashBase, targetId)
      treeRefreshTrigger.update((n) => n + 1)
      closeActions()
    } catch (e) {
      actionError = String(e)
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
            <KbViewerActionsMenu
              {actionsOpen}
              {deleteConfirm}
              {showRenameInput}
              {showCopyInput}
              {renameId}
              {copyTargetId}
              {actionError}
              onToggleMenu={toggleActionsMenu}
              onDelete={doDelete}
              onRename={doRename}
              onCopy={doCopy}
              onCancelDelete={() => (deleteConfirm = false)}
              onCancelRename={cancelRename}
              onCancelCopy={cancelCopy}
              onStartDeleteConfirm={startDeleteConfirm}
              onStartRename={startRename}
              onStartCopy={startCopy}
              onRenameIdChange={(value) => (renameId = value)}
              onCopyTargetIdChange={(value) => (copyTargetId = value)}
              onActionInputKeydown={handleActionInputKeydown}
            />
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
        <div class="kb-rendered-md" {@attach markdownClickAttach}>
          <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
          {@html rendered}
        </div>
      </article>
    {/if}

    {#if !editMode}
      <KbViewerMetaSection
        tags={item.tags}
        {linkedFrom}
        {metaOpen}
        {metaSummary}
        {tagsEditMode}
        {tagInput}
        {actionError}
        {viewerHashBase}
        onMetaOpenChange={(open) => (metaOpen = open)}
        onRemoveTag={removeTag}
        onAddTagFromInput={addTagFromInput}
        onStopTagsEdit={stopTagsEdit}
        onEnterTagsEdit={enterTagsEdit}
        onTagInputChange={(value) => (tagInput = value)}
        onActionInputKeydown={handleActionInputKeydown}
      />
    {/if}
  {/if}
</div>
