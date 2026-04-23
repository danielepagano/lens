<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import { getMountFilePath, getMountPreviewPath } from '../../services/api'

  export let path: string | null = null
  export let mode: 'attach' | 'manage' = 'manage'
  export let renaming: boolean = false
  export let renameValue: string = ''
  export let fullScreen: boolean = false

  const dispatch = createEventDispatcher<{
    attach: void
    download: void
    startRename: void
    confirmRename: string
    cancelRename: void
    delete: void
    upload: File
    close: void
  }>()

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
  const TEXT_EXTS = new Set(['.txt', '.md'])

  function ext(p: string): string {
    const dot = p.lastIndexOf('.')
    return dot >= 0 ? p.slice(dot).toLowerCase() : ''
  }

  $: fileExt = path ? ext(path) : ''
  $: isImage = path !== null && !isDir && IMAGE_EXTS.has(fileExt)
  $: isText = path !== null && TEXT_EXTS.has(fileExt)
  $: isVideo = path !== null && ['.mp4', '.webm', '.mov', '.avi'].includes(fileExt)
  $: isDir = path !== null && !fileExt
  $: filename = path ? path.split('/').pop() ?? path : ''

  let confirmDelete = false
  let renameInput: HTMLInputElement | null = null
  let fileInput: HTMLInputElement | null = null

  $: if (renaming && renameInput) {
    renameInput.focus()
    renameInput.select()
  }

  function handleRenameKey(e: KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); dispatch('confirmRename', renameValue) }
    if (e.key === 'Escape') { e.preventDefault(); dispatch('cancelRename') }
  }

  function handleDeleteClick() {
    if (confirmDelete) { dispatch('delete'); confirmDelete = false }
    else confirmDelete = true
  }

  function handleDeleteBlur() {
    confirmDelete = false
  }

  function handleUploadChange(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0]
    if (f) { dispatch('upload', f); (e.target as HTMLInputElement).value = '' }
  }

  function handleBackdropClick(e: MouseEvent) {
    if (fullScreen && e.target === e.currentTarget) dispatch('close')
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
<div
  class="spotlight-root"
  class:spotlight-fullscreen={fullScreen}
  on:click={handleBackdropClick}
>
  <div class="carousel-spotlight">
    {#if fullScreen}
      <button class="spotlight-close" type="button" aria-label="Close preview" on:click={() => dispatch('close')}>✕</button>
    {/if}

    {#if path === null}
      <span class="carousel-spotlight-placeholder">Select a file to preview</span>
    {:else if isImage}
      <img src={getMountFilePath(path)} alt={filename} />
    {:else if isVideo}
      <span class="carousel-spotlight-placeholder">🎬 {filename}</span>
    {:else if isText}
      <iframe
        src={getMountPreviewPath(path)}
        title={filename}
        class="spotlight-iframe"
        sandbox="allow-scripts allow-same-origin"
      />
    {:else if isDir}
      <span class="carousel-spotlight-placeholder">📁 {filename}</span>
    {:else}
      <span class="carousel-spotlight-placeholder">📄 {filename}</span>
    {/if}
  </div>

  <div class="carousel-actions">
    {#if mode === 'attach'}
      <button type="button" class="action-primary" disabled={!path || isDir} on:click={() => dispatch('attach')}>
        Attach after…
      </button>
    {/if}
    <button type="button" disabled={!path || isDir} on:click={() => dispatch('download')}>Download</button>
    <button type="button" disabled={!path} on:click={() => dispatch('startRename')}>Rename / Move</button>
    <button
      type="button"
      class:action-danger={confirmDelete}
      disabled={!path}
      on:click={handleDeleteClick}
      on:blur={handleDeleteBlur}
    >
      {confirmDelete ? 'Confirm delete?' : 'Delete'}
    </button>
    <label class="carousel-upload-label" aria-label="Upload a file">
      Upload
      <input
        bind:this={fileInput}
        type="file"
        class="sr-only"
        on:change={handleUploadChange}
      />
    </label>
  </div>

  {#if renaming}
    <div class="carousel-rename-row">
      <input
        bind:this={renameInput}
        bind:value={renameValue}
        type="text"
        placeholder="New name or path"
        on:keydown={handleRenameKey}
        aria-label="New file name or path"
      />
      <button type="button" on:click={() => dispatch('confirmRename', renameValue)}>OK</button>
      <button type="button" on:click={() => dispatch('cancelRename')}>Cancel</button>
    </div>
  {/if}
</div>

<style>
  .spotlight-root {
    display: contents;
  }
  .spotlight-fullscreen {
    display: flex;
    flex-direction: column;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.92);
    z-index: 300;
    overflow: auto;
  }
  .spotlight-fullscreen .carousel-spotlight {
    flex: 1;
    max-height: none;
  }
  .spotlight-fullscreen .carousel-actions {
    border-top: 1px solid var(--pico-muted-border-color);
    background: var(--pico-background-color);
  }
  .spotlight-close {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    background: rgba(0, 0, 0, 0.5);
    border: none;
    color: #fff;
    font-size: 1.2rem;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
  }
  .spotlight-iframe {
    width: 100%;
    height: 360px;
    border: none;
    border-radius: 4px;
  }
  .carousel-upload-label {
    display: inline-flex;
    align-items: center;
    padding: 0.4rem 0.85rem;
    font-size: 0.82rem;
    min-height: 34px;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid var(--pico-muted-border-color);
    background: transparent;
    color: inherit;
  }
  .carousel-upload-label:hover {
    background: var(--pico-secondary-background, #333);
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
</style>
