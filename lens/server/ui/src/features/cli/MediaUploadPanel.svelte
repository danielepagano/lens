<script lang="ts">
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { uploadMountFile } from '../../services/api'
  import { mediaUploadRequest, transactionResult, mountCacheRefreshTrigger } from '../../stores/ui'

  let file: File | null = null
  let error: string | null = null
  let uploading = false
  let dragOver = false

  $: isOpen = $mediaUploadRequest !== null
  $: dir = $mediaUploadRequest?.dir ?? ''
  $: displayDir = dir ? dir : '(mount root)'

  $: if (isOpen) {
    file = null
    error = null
    uploading = false
  }

  function handleClose() {
    mediaUploadRequest.set(null)
  }

  function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return
    file = fileList[0] ?? null
    error = null
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    dragOver = false
    handleFiles(e.dataTransfer?.files ?? null)
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    dragOver = true
  }

  function handleDragLeave() {
    dragOver = false
  }

  function handleBrowse(e: Event) {
    handleFiles((e.target as HTMLInputElement).files)
  }

  function handleDropZoneKey(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      document.getElementById('media-file-input')?.click()
    }
  }

  async function handleSubmit() {
    if (!file) { error = 'Select a file first.'; return }
    uploading = true
    error = null
    try {
      const result = await uploadMountFile(dir, file)
      if (result.status === 'ok') {
        mountCacheRefreshTrigger.update((n) => n + 1)
        mediaUploadRequest.set(null)
        transactionResult.set({
          title: 'Uploaded',
          message: `Uploaded: ${result.path ?? file.name}`,
          theme: 'info',
        })
      } else {
        error = result.detail ?? 'Upload failed'
      }
    } catch (err) {
      error = err instanceof Error ? err.message : String(err)
    } finally {
      uploading = false
    }
  }
</script>

<OutputPanel
  title="Upload media"
  theme="command"
  open={isOpen}
  streaming={false}
  autoClose={false}
  hasContent={true}
  showCancel={false}
  on:close={handleClose}
>
  <div slot="content" class="media-upload-panel">
    <p class="media-upload-dir">Destination: <code>{displayDir}</code></p>

    <div
      class="media-drop-zone"
      class:drag-over={dragOver}
      role="button"
      tabindex="0"
      aria-label="Drop zone — drag a file here or press Space/Enter to browse"
      on:drop={handleDrop}
      on:dragover={handleDragOver}
      on:dragleave={handleDragLeave}
      on:keydown={handleDropZoneKey}
    >
      {#if file}
        <span class="media-drop-filename">{file.name}</span>
      {:else}
        <span class="media-drop-hint">Drop a file here</span>
      {/if}
    </div>

    <label class="media-browse-label" for="media-file-input">Browse…</label>
    <input
      id="media-file-input"
      type="file"
      class="media-file-input-hidden"
      on:change={handleBrowse}
      aria-label="Browse for a file to upload"
    />

    {#if error}
      <p class="media-upload-error" role="alert">{error}</p>
    {/if}

    <button
      type="button"
      class="media-upload-btn"
      disabled={!file || uploading}
      on:click={handleSubmit}
    >
      {uploading ? 'Uploading…' : 'Upload'}
    </button>
  </div>
</OutputPanel>

<style>
  .media-upload-panel {
    padding: 0.75rem 1rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .media-upload-dir {
    margin: 0;
    font-size: 0.85rem;
    opacity: 0.8;
  }

  .media-drop-zone {
    border: 2px dashed var(--pico-muted-border-color, #555);
    border-radius: 6px;
    padding: 2rem 1rem;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    min-height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .media-drop-zone:focus {
    outline: 2px solid var(--pico-primary, #6c8ebf);
    outline-offset: 2px;
  }

  .media-drop-zone.drag-over {
    border-color: var(--pico-primary, #6c8ebf);
    background: var(--pico-primary-background, rgba(108, 142, 191, 0.08));
  }

  .media-drop-hint {
    opacity: 0.5;
    font-size: 0.9rem;
  }

  .media-drop-filename {
    font-size: 0.9rem;
    word-break: break-all;
  }

  .media-browse-label {
    display: inline-block;
    padding: 0.6rem 1.2rem;
    background: var(--pico-secondary-background, #333);
    border: 1px solid var(--pico-muted-border-color, #555);
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.9rem;
    text-align: center;
    min-height: 44px;
    line-height: 1.8;
  }

  .media-browse-label:hover {
    background: var(--pico-secondary-hover-background, #444);
  }

  .media-file-input-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }

  .media-upload-error {
    margin: 0;
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.85rem;
  }

  .media-upload-btn {
    padding: 0.65rem 1.4rem;
    min-height: 44px;
    font-size: 0.95rem;
    cursor: pointer;
    align-self: flex-start;
  }

  .media-upload-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
