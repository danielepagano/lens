<script lang="ts">
  import { onMount } from 'svelte'
  import { selectedKbId, kbDetailId, treeRefreshTrigger } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { currentProject } from '../../stores/project'
  import { stats } from '../../stores/stats'
  import {
    getKbItem,
    saveKbItem,
    saveKbItemSilent,
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
    attachKbDetailClicks,
    kbViewerHashBase,
    openKbItemInHash,
    renderKbMarkdown,
    stripKbItemFrontMatter,
    setKbDetailParam,
    toggleKbDetailsFlag,
  } from './kbViewerMarkdown'
  import type { KbLinkHandler } from './kbViewerMarkdown'
  import { attachKbEditableControls } from './kbEditableControls'
  import type { KbEditMeta } from './kbEditableControls'
  import KbViewerActionsMenu from './KbViewerActionsMenu.svelte'
  import KbViewerMetaSection from './KbViewerMetaSection.svelte'
  import KbDetailView from './KbDetailView.svelte'

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
  const kbDetails = $derived(item ? stripKbItemFrontMatter(item.content).frontMatter.kbDetails : false)
  const renderedResult = $derived(
    item
      ? renderKbMarkdown(item.content, $stats?.remember_pins_at_cursor ?? undefined, $currentProject, true)
      : { html: '', editMeta: [] as KbEditMeta[] },
  )
  const rendered = $derived(renderedResult.html)
  const editMeta = $derived(renderedResult.editMeta)
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

  const detailHandler: KbLinkHandler = (id: string) => {
    kbDetailId.set(id)
    setKbDetailParam(id)
  }

  const markdownClickAttach = $derived(
    kbDetails
      ? attachKbDetailClicks(detailHandler)
      : attachKbMarkdownClicks(viewerHashBase),
  )

  const editableControlsAttach = $derived(
    attachKbEditableControls(
      editMeta,
      () => item?.content ?? '',
      (newContent) => saveInlineEdit(newContent),
    ),
  )

  function saveInlineEdit(newContent: string) {
    if (!item) return
    item.content = newContent
    saveKbItemSilent(item.id, newContent)
  }

  let splitRatio = $state(0.5)
  let dragging = $state(false)

  function handleDividerMouseDown(e: MouseEvent) {
    e.preventDefault()
    const startY = e.clientY
    const startRatio = splitRatio
    const splitEl = (e.target as HTMLElement).closest('.kb-viewer-split') as HTMLElement | null
    if (!splitEl) return
    const panelHeight = splitEl.offsetHeight
    dragging = true

    function onMouseMove(ev: MouseEvent) {
      const dy = ev.clientY - startY
      splitRatio = Math.max(0.2, Math.min(0.8, startRatio + dy / panelHeight))
    }
    function onMouseUp() {
      dragging = false
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }

  function handleDividerTouchStart(e: TouchEvent) {
    const startY = e.touches[0]!.clientY
    const startRatio = splitRatio
    const splitEl = (e.target as HTMLElement).closest('.kb-viewer-split') as HTMLElement | null
    if (!splitEl) return
    const panelHeight = splitEl.offsetHeight
    dragging = true

    function onTouchMove(ev: TouchEvent) {
      const dy = ev.touches[0]!.clientY - startY
      splitRatio = Math.max(0.2, Math.min(0.8, startRatio + dy / panelHeight))
    }
    function onTouchEnd() {
      dragging = false
      document.removeEventListener('touchmove', onTouchMove)
      document.removeEventListener('touchend', onTouchEnd)
    }
    document.addEventListener('touchmove', onTouchMove, { passive: true })
    document.addEventListener('touchend', onTouchEnd)
  }



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

  let prevSelectedKbId: string | null = null
  onMount(() => {
    return selectedKbId.subscribe((id) => {
      activeLoadSeq += 1
      const loadSeq = activeLoadSeq
      // Clear detail only on actual change — not on the initial subscribe
      // (which fires during mount after stores are already populated from URL params).
      if (prevSelectedKbId !== null && prevSelectedKbId !== id) {
        kbDetailId.set(null)
      }
      prevSelectedKbId = id
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

  async function toggleDetail() {
    if (!item) return
    closeActions()
    const newContent = toggleKbDetailsFlag(item.content)
    try {
      await saveKbItem(item.id, newContent)
      item = { ...item, content: newContent }
      if (!kbDetails) {
        // turning on: if there's already a detail selected, preserve it
      } else {
        // turning off: clear detail
        kbDetailId.set(null)
        setKbDetailParam(null)
      }
      treeRefreshTrigger.update((n) => n + 1)
    } catch (e) {
      actionError = String(e)
    }
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
              {kbDetails}
              onToggleMenu={toggleActionsMenu}
              onDelete={doDelete}
              onRename={doRename}
              onCopy={doCopy}
              onToggleDetail={toggleDetail}
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
    {:else if kbDetails && $kbDetailId}
      <div class="kb-viewer-split" class:kb-viewer-split--dragging={dragging}>
        <div class="kb-viewer-split-pane kb-viewer-split-pane--main" style="flex:{splitRatio}">
          <article class="content kb-rendered">
            <div class="kb-rendered-md" {@attach markdownClickAttach} {@attach editableControlsAttach}>
              <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
              {@html rendered}
            </div>
          </article>
        </div>
        <div
          class="kb-viewer-split-divider"
          role="separator"
          tabindex="0"
          onmousedown={handleDividerMouseDown}
          ontouchstart={handleDividerTouchStart}
          onkeydown={(e) => {
            if (e.key === 'ArrowUp') splitRatio = Math.max(0.2, splitRatio - 0.02)
            if (e.key === 'ArrowDown') splitRatio = Math.min(0.8, splitRatio + 0.02)
          }}
        >
          <span class="kb-viewer-split-divider-grip"></span>
        </div>
        <div class="kb-viewer-split-pane kb-viewer-split-pane--detail" style="flex:{1 - splitRatio}">
          <KbDetailView />
        </div>
      </div>
    {:else}
      <article class="content kb-rendered">
        <div class="kb-rendered-md" {@attach markdownClickAttach} {@attach editableControlsAttach}>
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
