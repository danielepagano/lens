<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import { getMountFilePath, getMountPreviewPath } from '../../services/api'

  export let path: string | null = null
  export let mode: 'attach' | 'manage' = 'manage'
  export let renaming: boolean = false
  export let renameValue: string = ''

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
  $: spotlightFill = isText || isVideo

  let confirmDelete = false
  let renameInput: HTMLInputElement | null = null
  let fileInput: HTMLInputElement | null = null

  function selectBasename(input: HTMLInputElement) {
    const value = input.value
    const lastSlash = value.lastIndexOf('/')
    const start = lastSlash >= 0 ? lastSlash + 1 : 0
    const end = value.length
    input.setSelectionRange(start, end)
  }

  $: if (renaming && renameInput) {
    renameInput.focus()
    // Wait for bind:value to flush before selecting.
    requestAnimationFrame(() => {
      if (!renaming || !renameInput) return
      selectBasename(renameInput)
    })
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

  function handleUploadClick() {
    fileInput?.click()
  }
</script>

<!-- spotlight-root uses display:contents so children join carousel-body's flex context -->
<div class="spotlight-root">
  <div class="carousel-spotlight" class:spotlight-fill={spotlightFill}>
    {#if path === null}
      <span class="carousel-spotlight-placeholder">Select a file to preview</span>
    {:else}
      <button class="spotlight-close" type="button" aria-label="Deselect" on:click={() => dispatch('close')}>✕</button>
      <span class="spotlight-caption">{filename}</span>
      {#if isImage}
        <img src={getMountFilePath(path)} alt={filename} />
      {:else if isVideo}
        <!-- svelte-ignore a11y-media-has-caption -->
        <video src={getMountFilePath(path)} controls class="spotlight-video"></video>
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
    {/if}
  </div>

  <div class="carousel-actions">
    {#if mode === 'attach'}
      <button type="button" class="action-primary" disabled={!path || isDir} on:click={() => dispatch('attach')}>
        Attach
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
    <button type="button" on:click={handleUploadClick}>Upload</button>
    <input bind:this={fileInput} type="file" class="sr-only" on:change={handleUploadChange} />
  </div>

  {#if renaming}
    <div class="carousel-rename-row">
      <input
        bind:this={renameInput}
        bind:value={renameValue}
        type="text"
        placeholder="New name, or path/to/name to move"
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
  .spotlight-iframe, .spotlight-video {
    flex: 1;
    min-height: 0;
    width: 100%;
    border: none;
    border-radius: 0;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }
  .spotlight-close {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    background: rgba(0, 0, 0, 0.45);
    border: none;
    color: #fff;
    font-size: 1rem;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
    opacity: 0.75;
  }
  .spotlight-close:hover {
    opacity: 1;
  }
  .spotlight-caption {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 0.3rem 0.75rem;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.65));
    color: #fff;
    font-size: 0.72rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: center;
    pointer-events: none;
  }
</style>
