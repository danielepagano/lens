<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import { mediaCarouselRequest, mountCacheRefreshTrigger } from '../../stores/ui'
  import {
    browseMountDir,
    attachFile,
    deleteMountPath,
    moveMountFile,
    uploadMountFile,
    getMountFilePath,
  } from '../../services/api'
  import MediaStrip from './MediaStrip.svelte'
  import MediaSpotlight from './MediaSpotlight.svelte'

  const dispatch = createEventDispatcher<{ done: void }>()

  let currentDir = ''
  let entries: { name: string; is_dir: boolean }[] = []
  let selectedIndex = -1
  let loading = false
  let error: string | null = null
  let renaming = false
  let renameValue = ''
  let uploading = false
  let dragActive = false

  $: request = $mediaCarouselRequest
  $: mode = request?.mode ?? 'manage'
  $: title = mode === 'attach' ? 'Attach Media' : 'Manage Media'
  $: if (request !== null) open(request.dir)

  async function open(dir: string) {
    currentDir = dir
    selectedIndex = -1
    renaming = false
    error = null
    await loadDir()
  }

  async function loadDir() {
    loading = true
    error = null
    try {
      entries = await browseMountDir(currentDir)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      entries = []
    } finally {
      loading = false
    }
  }

  function close() {
    mediaCarouselRequest.set(null)
    renaming = false
  }

  $: breadcrumbs = currentDir
    ? currentDir.split('/').filter(Boolean).map((seg, i, arr) => ({
        label: seg,
        path: arr.slice(0, i + 1).join('/'),
      }))
    : []

  async function navigateTo(dir: string) {
    currentDir = dir
    selectedIndex = -1
    renaming = false
    await loadDir()
  }

  function handleNavigate(e: CustomEvent<string>) {
    const dir = currentDir ? `${currentDir}/${e.detail}` : e.detail
    navigateTo(dir)
  }

  function handleSelect(e: CustomEvent<number>) {
    selectedIndex = e.detail
    renaming = false
  }

  function handlePreview(e: CustomEvent<number>) {
    selectedIndex = e.detail
  }

  $: selectedEntry = selectedIndex >= 0 ? entries[selectedIndex] : null
  $: selectedPath = selectedEntry && !selectedEntry.is_dir
    ? (currentDir ? `${currentDir}/${selectedEntry.name}` : selectedEntry.name)
    : null

  async function handleAttach() {
    if (!selectedPath || !request) return
    error = null
    try {
      const result = await attachFile(selectedPath, {
        ...(request.attachAddress ? { address: request.attachAddress } : {}),
        ...(request.attachLine !== undefined ? { line: request.attachLine } : {}),
      })
      if (result.status === 'ok') { close(); dispatch('done'); return }
      error = result.detail ?? 'Attach failed'
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  function handleDownload() {
    if (!selectedPath) return
    const a = document.createElement('a')
    a.href = getMountFilePath(selectedPath)
    a.download = selectedPath.split('/').pop() ?? selectedPath
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  function handleStartRename() {
    if (!selectedPath) return
    renameValue = selectedPath
    renaming = true
  }

  async function handleConfirmRename(e: CustomEvent<string>) {
    if (!selectedPath) return
    const newName = e.detail.trim()
    if (!newName) { renaming = false; return }
    const newPath = newName.includes('/') ? newName : (currentDir ? `${currentDir}/${newName}` : newName)
    error = null
    try {
      const result = await moveMountFile(selectedPath, newPath)
      if (result.status === 'ok') {
        renaming = false
        mountCacheRefreshTrigger.update(n => n + 1)
        await loadDir()
        return
      }
      error = result.detail ?? 'Rename failed'
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
    renaming = false
  }

  async function handleDelete() {
    if (!selectedPath) return
    error = null
    try {
      await deleteMountPath(selectedPath)
      selectedIndex = -1
      mountCacheRefreshTrigger.update(n => n + 1)
      await loadDir()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  async function handleUpload(e: CustomEvent<File> | File) {
    const file = e instanceof CustomEvent ? e.detail : e
    uploading = true
    error = null
    try {
      const result = await uploadMountFile(currentDir, file)
      if (result.status === 'ok') {
        mountCacheRefreshTrigger.update(n => n + 1)
        await loadDir()
        const idx = entries.findIndex(en => en.name === (result.path ?? '').split('/').pop())
        if (idx >= 0) selectedIndex = idx
      } else {
        error = result.detail ?? 'Upload failed'
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    } finally {
      uploading = false
    }
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    dragActive = true
  }

  function handleDragLeave(e: DragEvent) {
    if ((e.currentTarget as Element).contains(e.relatedTarget as Node)) return
    dragActive = false
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    dragActive = false
    const file = e.dataTransfer?.files?.[0]
    if (file) handleUpload(file)
  }
</script>

{#if request !== null}
  <div
    class="carousel-overlay"
    class:carousel-drop-active={dragActive}
    on:dragover={handleDragOver}
    on:dragleave={handleDragLeave}
    on:drop={handleDrop}
    role="dialog"
    aria-modal="true"
    aria-label={title}
  >
    <div class="carousel-header">
      <div class="carousel-header-top">
        <span class="carousel-title">{title}</span>
        <button type="button" class="carousel-close" aria-label="Close" on:click={close}>✕</button>
      </div>
      <nav class="carousel-path" aria-label="Folder path">
        <button type="button" on:click={() => navigateTo('')}>Root</button>
        {#each breadcrumbs as crumb (crumb.path)}
          <span aria-hidden="true"> / </span>
          <button type="button" on:click={() => navigateTo(crumb.path)}>{crumb.label}</button>
        {/each}
      </nav>
    </div>

    <div class="carousel-body">
      {#if loading}
        <div class="carousel-loading">Loading…</div>
      {:else}
        <MediaStrip
          {entries}
          {selectedIndex}
          {currentDir}
          compact={selectedPath !== null}
          on:select={handleSelect}
          on:navigate={handleNavigate}
          on:preview={handlePreview}
        />
      {/if}

      {#if selectedPath !== null}
        <MediaSpotlight
          path={selectedPath}
          {mode}
          {renaming}
          {renameValue}
          on:attach={handleAttach}
          on:download={handleDownload}
          on:startRename={handleStartRename}
          on:confirmRename={handleConfirmRename}
          on:cancelRename={() => { renaming = false }}
          on:delete={handleDelete}
          on:upload={handleUpload}
          on:close={() => { selectedIndex = -1 }}
        />
      {/if}

      {#if uploading}
        <div class="carousel-uploading">Uploading…</div>
      {/if}
      {#if error}
        <div class="carousel-error" role="alert">{error}</div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .carousel-loading, .carousel-uploading {
    padding: 1rem;
    opacity: 0.6;
    font-size: 0.85rem;
  }
  .carousel-error {
    padding: 0.5rem 0.9rem;
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.85rem;
    flex-shrink: 0;
  }
  .carousel-close {
    background: none;
    border: none;
    font-size: 1.1rem;
    cursor: pointer;
    padding: 0.2rem 0.5rem;
    opacity: 0.7;
    min-height: 34px;
  }
  .carousel-close:hover { opacity: 1; }
</style>
