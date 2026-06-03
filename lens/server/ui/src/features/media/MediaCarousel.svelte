<script lang="ts">
  import type { MediaCarouselRequest } from '../../stores/ui'
  import { mediaCarouselRequest, mountCacheRefreshTrigger } from '../../stores/ui'
  import {
    browseMountDir,
    attachFile,
    deleteMountPath,
    moveMountFile,
    uploadMountFile,
    getMountFilePath,
    runEdit,
    StreamBusyError,
    type MountEntry,
  } from '../../services/api'
  import { buildMountEmbedLine } from '../../utils/mountEmbed'
  import MediaStrip from './MediaStrip.svelte'
  import MediaSpotlight from './MediaSpotlight.svelte'

  type MediaCarouselProps = {
    onDone?: () => void
  }

  let { onDone }: MediaCarouselProps = $props()

  let currentDir = $state('')
  let entries = $state.raw<MountEntry[]>([])
  let selectedIndex = $state(-1)
  let loading = $state(false)
  let error = $state<string | null>(null)
  let renaming = $state(false)
  let renameValue = $state('')
  let uploading = $state(false)
  let removing = $state(false)
  let dragActive = $state(false)
  let uploadInput = $state<HTMLInputElement | null>(null)

  let request = $derived($mediaCarouselRequest)
  let mode = $derived(request?.mode ?? 'manage')
  let title = $derived(
    mode === 'attach' ? 'Attach Media' : mode === 'replace' ? 'Replace Media' : 'Manage Media'
  )

  let lastRequest: MediaCarouselRequest | null = null
  $effect(() => {
    if (request === null) {
      lastRequest = null
      return
    }
    if (request !== lastRequest) {
      lastRequest = request
      void open(request.dir)
    }
  })

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

  let breadcrumbs = $derived.by(() =>
    currentDir
      ? currentDir.split('/').filter(Boolean).map((seg, i, arr) => ({
          label: seg,
          path: arr.slice(0, i + 1).join('/'),
        }))
      : []
  )

  async function navigateTo(dir: string) {
    currentDir = dir
    selectedIndex = -1
    renaming = false
    await loadDir()
  }

  function handleNavigate(name: string) {
    const dir = currentDir ? `${currentDir}/${name}` : name
    navigateTo(dir)
  }

  function handleSelect(index: number) {
    selectedIndex = index
    renaming = false
  }

  function handlePreview(index: number) {
    selectedIndex = index
  }

  let selectedEntry = $derived(selectedIndex >= 0 ? entries[selectedIndex] ?? null : null)
  let selectedPath = $derived(
    selectedEntry && !selectedEntry.is_dir
      ? (currentDir ? `${currentDir}/${selectedEntry.name}` : selectedEntry.name)
      : null
  )

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
  function pathExt(p: string): string {
    const dot = p.lastIndexOf('.')
    return dot >= 0 ? p.slice(dot).toLowerCase() : ''
  }
  let selectedIsImage = $derived(!!(selectedPath && IMAGE_EXTS.has(pathExt(selectedPath))))

  let imageChromeless = $state(false)
  let prevSpotlightPath: string | null = null
  $effect(() => {
    if (selectedPath !== prevSpotlightPath) {
      prevSpotlightPath = selectedPath
      imageChromeless = false
    }
  })

  function handleToggleImageChromeless() {
    if (!selectedIsImage) return
    imageChromeless = !imageChromeless
  }

  async function handleAttach() {
    if (!selectedPath || !request) return
    error = null
    if (request.mode === 'replace') {
      const addr = request.attachAddress
      const ln = request.replaceImageLine
      if (addr === undefined || ln === undefined) return
      try {
        const replacement = buildMountEmbedLine(selectedPath)
        const result = await runEdit(
          {
            address: addr,
            start_line: ln,
            end_line: ln,
            prompt: replacement,
            replace: true,
          },
          () => {}
        )
        if (result.type === 'error') {
          error = result.message
          return
        }
        close()
        onDone?.()
      } catch (e) {
        if (e instanceof StreamBusyError) {
          error = e.message
          return
        }
        error = e instanceof Error ? e.message : String(e)
      }
      return
    }
    try {
      const result = await attachFile(selectedPath, {
        ...(request.attachAddress ? { address: request.attachAddress } : {}),
        ...(request.attachLine !== undefined ? { line: request.attachLine } : {}),
      })
      if (result.status === 'ok') {
        close()
        onDone?.()
        return
      }
      error = result.detail ?? 'Attach failed'
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  async function handleRemoveFromScene() {
    if (!request || request.mode !== 'replace') return
    const addr = request.attachAddress
    const ln = request.replaceImageLine
    if (addr === undefined || ln === undefined) return
    removing = true
    error = null
    try {
      const result = await runEdit(
        {
          address: addr,
          start_line: ln,
          end_line: ln,
          prompt: '',
          replace: true,
        },
        () => {}
      )
      if (result.type === 'error') {
        error = result.message
        return
      }
      close()
      onDone?.()
    } catch (e) {
      if (e instanceof StreamBusyError) {
        error = e.message
        return
      }
      error = e instanceof Error ? e.message : String(e)
    } finally {
      removing = false
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

  async function handleConfirmRename(newNameRaw: string) {
    if (!selectedPath) return
    const newName = newNameRaw.trim()
    if (!newName) {
      renaming = false
      return
    }
    const newPath = newName.includes('/') ? newName : (currentDir ? `${currentDir}/${newName}` : newName)
    error = null
    try {
      const result = await moveMountFile(selectedPath, newPath)
      if (result.status === 'ok') {
        renaming = false
        mountCacheRefreshTrigger.update((n) => n + 1)
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
      mountCacheRefreshTrigger.update((n) => n + 1)
      await loadDir()
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
    }
  }

  async function handleUpload(file: File) {
    uploading = true
    error = null
    try {
      const result = await uploadMountFile(currentDir, file)
      if (result.status === 'ok') {
        mountCacheRefreshTrigger.update((n) => n + 1)
        await loadDir()
        const idx = entries.findIndex((en) => en.name === (result.path ?? '').split('/').pop())
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

  function handleUploadButtonClick() {
    uploadInput?.click()
  }

  function handleUploadInputChange(e: Event) {
    const input = e.currentTarget as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return
    void handleUpload(file)
    input.value = ''
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
    class={[
      'carousel-overlay',
      imageChromeless && 'carousel-image-only',
      dragActive && 'carousel-drop-active',
    ]}
    ondragover={handleDragOver}
    ondragleave={handleDragLeave}
    ondrop={handleDrop}
    role="dialog"
    tabindex="-1"
    aria-modal="true"
    aria-label={title}
  >
    <div class="carousel-header">
      <div class="carousel-header-top">
        <span class="carousel-title">{title}</span>
        <button type="button" class="carousel-close" aria-label="Close" onclick={close}>✕</button>
      </div>
      <nav class="carousel-path" aria-label="Folder path">
        <button type="button" onclick={() => navigateTo('')}>Root</button>
        {#each breadcrumbs as crumb (crumb.path)}
          <span aria-hidden="true"> / </span>
          <button type="button" onclick={() => navigateTo(crumb.path)}>{crumb.label}</button>
        {/each}
      </nav>
    </div>

    <div class="carousel-body">
      {#if loading}
        <div class="carousel-loading">Loading…</div>
      {:else}
        <div
          class="carousel-strip-wrap"
          style="flex: {selectedPath !== null ? '0 0 auto' : '1 1 auto'}"
        >
          <MediaStrip
            {entries}
            {selectedIndex}
            {currentDir}
            compact={selectedPath !== null}
            onSelect={handleSelect}
            onNavigate={handleNavigate}
            onPreview={handlePreview}
          />

          {#if selectedPath === null}
            {#if mode === 'replace' && request.attachAddress !== undefined && request.replaceImageLine !== undefined}
              <button
                type="button"
                class="carousel-remove-scene-btn"
                aria-label="Clear media from passage"
                title="Clear scene image from this passage (does not delete the mount file)"
                disabled={uploading || removing}
                onclick={() => {
                  void handleRemoveFromScene()
                }}
              >Clear Media</button>
            {/if}
            <button
              type="button"
              class="carousel-upload-btn"
              aria-label="Upload file"
              title="Upload file"
              disabled={uploading || removing}
              onclick={handleUploadButtonClick}
            >+</button>
            <input
              bind:this={uploadInput}
              type="file"
              class="sr-only"
              onchange={handleUploadInputChange}
            />
          {/if}
        </div>
      {/if}

      {#if selectedPath !== null}
        <MediaSpotlight
          path={selectedPath}
          mode={mode === 'replace' ? 'replace' : mode}
          {renaming}
          {renameValue}
          chromeless={imageChromeless}
          onAttach={handleAttach}
          onDownload={handleDownload}
          onStartRename={handleStartRename}
          onConfirmRename={handleConfirmRename}
          onCancelRename={() => {
            renaming = false
          }}
          onDelete={handleDelete}
          onClose={() => {
            selectedIndex = -1
          }}
          onToggleChromeless={handleToggleImageChromeless}
        />
      {/if}

      {#if uploading}
        <div class="carousel-uploading">Uploading…</div>
      {/if}
      {#if removing}
        <div class="carousel-uploading">Removing…</div>
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

  .carousel-remove-scene-btn {
    position: absolute;
    left: 0.65rem;
    bottom: 0.65rem;
    min-height: 40px;
    padding: 0 0.55rem;
    border-radius: var(--pico-border-radius);
    border: 1px solid var(--pico-del-color, #e05c5c);
    background: rgba(5, 5, 10, 0.55);
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
    z-index: 5;
    backdrop-filter: blur(8px);
  }

  .carousel-remove-scene-btn:hover:not(:disabled) {
    filter: brightness(1.08);
  }

  .carousel-remove-scene-btn:active:not(:disabled) {
    transform: translateY(1px);
  }

  .carousel-remove-scene-btn:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .carousel-remove-scene-btn:focus-visible {
    outline: 2px solid var(--pico-del-color, #e05c5c);
    outline-offset: 2px;
  }

  .carousel-strip-wrap {
    position: relative;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .carousel-upload-btn {
    position: absolute;
    right: 0.65rem;
    bottom: 0.65rem;
    width: 40px;
    height: 40px;
    border-radius: 999px;
    border: 1px solid var(--pico-muted-border-color);
    background: var(--pico-card-background-color);
    color: var(--pico-primary);
    font-size: 1.35rem;
    line-height: 1;
    padding: 0;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
    z-index: 5;
  }

  .carousel-upload-btn:hover { filter: brightness(1.05); }
  .carousel-upload-btn:active { transform: translateY(1px); }
  .carousel-upload-btn:disabled { opacity: 0.55; cursor: default; }
  .carousel-upload-btn:focus-visible {
    outline: 2px solid var(--pico-primary);
    outline-offset: 2px;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
</style>
