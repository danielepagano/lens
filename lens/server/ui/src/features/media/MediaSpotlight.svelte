<script lang="ts">
  import { onMount } from 'svelte'
  import { fetchMountFileText, getMountFilePath, getMountPreviewPath } from '../../services/api'

  type MediaSpotlightMode = 'attach' | 'manage' | 'preview' | 'replace'

  type MediaSpotlightProps = {
    path?: string | null
    refCopyPath?: string | null
    mode?: MediaSpotlightMode
    previewSrc?: string | null
    saved?: boolean
    saving?: boolean
    renaming?: boolean
    renameValue?: string
    chromeless?: boolean
    onAttach?: () => void
    onDownload?: () => void
    onStartRename?: () => void
    onConfirmRename?: (value: string) => void
    onCancelRename?: () => void
    onDelete?: () => void
    onClose?: () => void
    onSave?: () => void
    onToggleChromeless?: () => void
  }

  let {
    path = null,
    refCopyPath = null,
    mode = 'manage',
    previewSrc = null,
    saved = false,
    saving = false,
    renaming = false,
    renameValue = '',
    chromeless = false,
    onAttach,
    onDownload,
    onStartRename,
    onConfirmRename,
    onCancelRename,
    onDelete,
    onClose,
    onSave,
    onToggleChromeless,
  }: MediaSpotlightProps = $props()

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
  const PLAIN_PRE_EXTS = new Set(['.txt', '.json', '.yaml', '.yml'])

  function ext(p: string): string {
    const dot = p.lastIndexOf('.')
    return dot >= 0 ? p.slice(dot).toLowerCase() : ''
  }

  let fileExt = $derived(path ? ext(path) : '')
  let isDir = $derived(path !== null && !fileExt)
  let isAudio = $derived(path !== null && ['.mp3', '.wav'].includes(fileExt))
  let isImage = $derived(path !== null && !isDir && IMAGE_EXTS.has(fileExt))
  let isPlainPre = $derived(path !== null && PLAIN_PRE_EXTS.has(fileExt))
  let isMarkdownPreview = $derived(path !== null && fileExt === '.md')
  let isVideo = $derived(path !== null && ['.mp4', '.webm', '.mov', '.avi'].includes(fileExt))
  let filename = $derived(path ? path.split('/').pop() ?? path : '')
  let pathToCopy = $derived(
    path !== null && !isDir ? (mode === 'preview' ? refCopyPath : path) : null
  )
  let spotlightFill = $derived(isPlainPre || isMarkdownPreview || isVideo || isAudio)
  let imageSrc = $derived(previewSrc ?? (path ? getMountFilePath(path) : ''))

  let plainPreviewPath = $state<string | null>(null)
  let plainPreviewText = $state('')
  let plainPreviewError = $state<string | null>(null)
  let plainPreviewLoading = $state(false)
  let plainFetchSeq = 0

  async function loadPlainPreview(p: string) {
    const seq = ++plainFetchSeq
    plainPreviewLoading = true
    plainPreviewError = null
    plainPreviewText = ''
    try {
      const t = await fetchMountFileText(p)
      if (seq !== plainFetchSeq) return
      plainPreviewText = t
    } catch (e) {
      if (seq !== plainFetchSeq) return
      plainPreviewError = e instanceof Error ? e.message : String(e)
    } finally {
      if (seq === plainFetchSeq) plainPreviewLoading = false
    }
  }

  $effect(() => {
    if (isPlainPre && path && path !== plainPreviewPath) {
      plainPreviewPath = path
      void loadPlainPreview(path)
      return
    }

    if ((!isPlainPre || !path) && plainPreviewPath !== null) {
      plainFetchSeq += 1
      plainPreviewPath = null
      plainPreviewText = ''
      plainPreviewError = null
      plainPreviewLoading = false
    }
  })

  let imageFullRes = $state(false)
  let lastPath: string | null = null
  let coarsePointer = $state(
    typeof globalThis !== 'undefined' &&
    typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(pointer: coarse)').matches
  )

  $effect(() => {
    if (path !== lastPath) {
      imageFullRes = false
      lastPath = path
    }
  })

  onMount(() => {
    const mql = window.matchMedia('(pointer: coarse)')
    coarsePointer = mql.matches
    if (mql.matches) imageFullRes = false
    const onChange = () => {
      coarsePointer = mql.matches
      if (mql.matches) imageFullRes = false
    }
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  })

  let imageStageEl = $state<HTMLDivElement | null>(null)

  let confirmDelete = $state(false)
  let renameInput = $state<HTMLInputElement | null>(null)
  let renameDraft = $state('')
  let renameExtension = $state('')
  let renameFocusKey: string | null = null

  function finalSegmentExt(pathOrName: string): string {
    const lastSlash = pathOrName.lastIndexOf('/')
    const base = lastSlash >= 0 ? pathOrName.slice(lastSlash + 1) : pathOrName
    const dot = base.lastIndexOf('.')
    return dot >= 0 ? base.slice(dot) : ''
  }

  function stripFinalExt(pathOrName: string): string {
    const ext = finalSegmentExt(pathOrName)
    if (!ext) return pathOrName
    const lastSlash = pathOrName.lastIndexOf('/')
    const dir = lastSlash >= 0 ? pathOrName.slice(0, lastSlash + 1) : ''
    const base = lastSlash >= 0 ? pathOrName.slice(lastSlash + 1) : pathOrName
    return dir + base.slice(0, -ext.length)
  }

  function appendFinalExt(pathOrName: string, ext: string): string {
    if (!ext) return pathOrName
    const lastSlash = pathOrName.lastIndexOf('/')
    const dir = lastSlash >= 0 ? pathOrName.slice(0, lastSlash + 1) : ''
    const base = lastSlash >= 0 ? pathOrName.slice(lastSlash + 1) : pathOrName
    return dir + base + ext
  }

  function selectBasename(input: HTMLInputElement) {
    const value = input.value
    const lastSlash = value.lastIndexOf('/')
    const start = lastSlash >= 0 ? lastSlash + 1 : 0
    const end = value.length
    input.setSelectionRange(start, end)
  }

  function confirmRename() {
    const stemPath = renameDraft.trim()
    if (!stemPath) {
      onCancelRename?.()
      return
    }
    onConfirmRename?.(appendFinalExt(stemPath, renameExtension))
  }

  $effect(() => {
    if (!renaming) {
      renameFocusKey = null
      renameExtension = ''
      return
    }

    renameExtension = finalSegmentExt(renameValue)
    renameDraft = stripFinalExt(renameValue)

    if (!renameInput) return

    const nextFocusKey = `${path ?? ''}:${renameValue}`
    if (renameFocusKey === nextFocusKey) return

    renameFocusKey = nextFocusKey
    renameInput.focus()

    // Wait for bind:value to flush before selecting.
    requestAnimationFrame(() => {
      if (!renaming || !renameInput) return
      selectBasename(renameInput)
    })
  })

  function handleRenameKey(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault()
      confirmRename()
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      onCancelRename?.()
    }
  }

  function handleDeleteClick() {
    if (confirmDelete) {
      onDelete?.()
      confirmDelete = false
    }
    else confirmDelete = true
  }

  function handleDeleteBlur() {
    confirmDelete = false
  }

  async function handleCopyMountPath() {
    if (!pathToCopy) return
    try {
      await navigator.clipboard.writeText(pathToCopy)
    } catch {
      try {
        const ta = document.createElement('textarea')
        ta.value = pathToCopy
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      } catch {
        /* ignore */
      }
    }
  }

  function toggleImageFullRes() {
    if (!isImage) return
    imageFullRes = !imageFullRes
    if (imageFullRes) {
      requestAnimationFrame(() => {
        if (!imageStageEl) return
        imageStageEl.scrollTop = 0
        imageStageEl.scrollLeft = 0
      })
    }
  }

  function handleImageKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggleImageFullRes()
    } else if (e.key === 'Escape' && imageFullRes && !chromeless) {
      e.preventDefault()
      imageFullRes = false
    }
  }

  function handleChromelessWindowKey(e: KeyboardEvent) {
    if (!chromeless || !isImage || e.key !== 'Escape') return
    if (imageFullRes) {
      imageFullRes = false
      e.preventDefault()
      return
    }
    onToggleChromeless?.()
    e.preventDefault()
  }

  function handleSpotlightCloseClick() {
    if (chromeless && isImage) onToggleChromeless?.()
    else onClose?.()
  }

  function handleChromelessButtonClick(event: MouseEvent) {
    event.stopPropagation()
    onToggleChromeless?.()
  }
</script>

<svelte:window onkeydown={handleChromelessWindowKey} />

<!-- spotlight-root uses display:contents so children join carousel-body's flex context -->
<div class="spotlight-root">
  <div
    class={[
      'carousel-spotlight',
      { 'spotlight-fill': spotlightFill, 'spotlight-has-image': isImage },
    ]}
  >
    {#if path === null}
      <span class="carousel-spotlight-placeholder">Select a file to preview</span>
    {:else}
      <button
        class="spotlight-close"
        type="button"
        aria-label={chromeless && isImage ? 'Show carousel' : 'Deselect'}
        onclick={handleSpotlightCloseClick}
      >✕</button>
      {#if isImage && path && !chromeless && !coarsePointer}
        <button
          type="button"
          class="spotlight-chromeless-btn"
          aria-label="Focus image — hide carousel"
          onclick={handleChromelessButtonClick}
        >⛶</button>
      {/if}
      {#if isAudio}
        <audio
          src={imageSrc}
          controls
          preload="metadata"
          class="spotlight-audio"
        ></audio>
      {:else if isImage}
        {#if coarsePointer}
          <div class="spotlight-image-stage">
            <div class="spotlight-image-static">
              <img src={imageSrc} alt={filename} />
            </div>
          </div>
        {:else}
          <div
            bind:this={imageStageEl}
            class={['spotlight-image-stage', { fullres: imageFullRes }]}
          >
            <button
              type="button"
              class="spotlight-image-btn"
              aria-label={imageFullRes ? 'Exit full resolution view' : 'View at full resolution'}
              aria-pressed={imageFullRes}
              onclick={toggleImageFullRes}
              onkeydown={handleImageKeyDown}
            >
              <img src={imageSrc} alt={filename} />
            </button>
          </div>
        {/if}
      {:else if isVideo}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          src={getMountFilePath(path)}
          controls
          playsinline
          preload="metadata"
          class="spotlight-video"
        ></video>
      {:else if isPlainPre}
        <div class="spotlight-plain-wrap">
          {#if plainPreviewLoading}
            <span class="carousel-spotlight-placeholder">Loading…</span>
          {:else if plainPreviewError}
            <span class="carousel-spotlight-placeholder" role="alert">{plainPreviewError}</span>
          {:else}
            <pre class="spotlight-plain">{plainPreviewText}</pre>
          {/if}
        </div>
      {:else if isMarkdownPreview}
        <iframe
          src={getMountPreviewPath(path)}
          title={filename}
          class="spotlight-iframe"
          sandbox="allow-scripts allow-same-origin"
        ></iframe>
      {:else if isDir}
        <span class="carousel-spotlight-placeholder">📁 {filename}</span>
      {:else}
        <span class="carousel-spotlight-placeholder">📄 {filename}</span>
      {/if}
    {/if}
  </div>

  {#if !(chromeless && isImage)}
  <div class="carousel-actions">
    {#if path !== null}
      <div class="carousel-actions-filename-row">
        <div class="carousel-actions-filename" title={pathToCopy ?? filename}>{filename}</div>
        {#if pathToCopy}
          <button
            type="button"
            class="carousel-copy-path"
            title="Copy mount-relative path (for example --ref)"
            onclick={handleCopyMountPath}
          >Copy path</button>
        {/if}
      </div>
    {/if}
    {#if mode === 'attach'}
      <button type="button" class="action-primary" disabled={!path || isDir} onclick={() => onAttach?.()}>
        Attach
      </button>
    {/if}
    {#if mode === 'replace'}
      <button type="button" class="action-primary" disabled={!path || isDir} onclick={() => onAttach?.()}>
        Replace
      </button>
    {/if}
    {#if mode === 'preview'}
      <button
        type="button"
        class="action-primary"
        disabled={saving || saved || !previewSrc}
        onclick={() => onSave?.()}
      >
        {saved ? 'Saved' : saving ? 'Saving…' : 'Save'}
      </button>
    {/if}
    {#if mode !== 'preview'}
    <button type="button" disabled={!path || isDir} onclick={() => onDownload?.()}>Download</button>
    <button type="button" disabled={!path} onclick={() => onStartRename?.()}>Rename / Move</button>
    <button
      type="button"
      class={{ 'action-danger': confirmDelete }}
      disabled={!path}
      onclick={handleDeleteClick}
      onblur={handleDeleteBlur}
    >
      {confirmDelete ? 'Confirm delete?' : 'Delete'}
    </button>
    {/if}
  </div>
  {/if}

  {#if renaming && !(chromeless && isImage)}
    <div class="carousel-rename-row">
      <div class="carousel-rename-field">
        <input
          bind:this={renameInput}
          bind:value={renameDraft}
          type="text"
          placeholder="New name, or path/to/name to move"
          onkeydown={handleRenameKey}
          aria-label={renameExtension
            ? `New file name or path (extension ${renameExtension} is fixed)`
            : 'New file name or path'}
        />
        {#if renameExtension}
          <span class="carousel-rename-ext" aria-hidden="true">{renameExtension}</span>
        {/if}
      </div>
      <button type="button" onclick={confirmRename}>OK</button>
      <button type="button" onclick={() => onCancelRename?.()}>Cancel</button>
    </div>
  {/if}
</div>

<style>
  .spotlight-root {
    display: contents;
  }
  .spotlight-iframe, .spotlight-video, .spotlight-audio {
    flex: 1;
    min-height: 0;
    width: 100%;
    border: none;
    border-radius: 0;
  }
  .spotlight-audio {
    align-self: center;
    max-height: 4rem;
  }
  .spotlight-plain-wrap {
    flex: 1;
    min-height: 0;
    width: 100%;
    overflow: auto;
    padding: 0.5rem 0.75rem;
    box-sizing: border-box;
  }
  .spotlight-plain {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.8rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
  /* Image preview: bounded stage so fit uses real viewport; full-res scrolls inside stage only. */
  :global(.carousel-spotlight.spotlight-has-image) {
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    overflow: hidden;
    padding: 0px;
  }
  /* Fit mode: button must fill the stage so img max-height % resolves against real bounds (not content-sized). */
  .spotlight-image-stage {
    flex: 1;
    min-height: 0;
    min-width: 0;
    width: 100%;
    display: flex;
    flex-direction: row;
    align-items: stretch;
    overflow: hidden;
  }
  .spotlight-image-static {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    width: 100%;
    align-self: stretch;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
  }
  .spotlight-image-static :global(img) {
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
    border-radius: 4px;
  }
  .spotlight-image-stage:not(.fullres) .spotlight-image-btn {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 0;
    width: 100%;
    align-self: stretch;
  }
  .spotlight-image-stage.fullres {
    flex-direction: row;
    align-items: flex-start;
    justify-content: flex-start;
    overflow: auto;
  }
  .spotlight-image-btn {
    all: unset;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: zoom-in;
    outline: none;
    border-radius: 4px;
  }
  .spotlight-image-btn:focus-visible {
    outline: 2px solid var(--pico-primary);
    outline-offset: 2px;
  }
  .spotlight-image-stage.fullres .spotlight-image-btn {
    max-width: none;
    max-height: none;
  }
  .spotlight-image-btn :global(img) {
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
    border-radius: 4px;
    cursor: zoom-in;
  }
  .spotlight-image-stage.fullres .spotlight-image-btn :global(img) {
    max-width: none;
    max-height: none;
    cursor: zoom-out;
  }
  .carousel-actions-filename-row {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex: 1 1 100%;
    width: 100%;
    min-width: 0;
    padding-bottom: 0.15rem;
    margin-bottom: 0.15rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .carousel-actions-filename {
    flex: 1 1 auto;
    min-width: 0;
    font-size: 0.72rem;
    line-height: 1.2;
    opacity: 0.85;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .carousel-copy-path {
    flex-shrink: 0;
    font-size: 0.68rem !important;
    padding: 0.1rem 0.35rem !important;
    min-height: 28px !important;
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
  .spotlight-chromeless-btn {
    position: absolute;
    top: 0.5rem;
    left: 0.5rem;
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
    line-height: 1;
    padding: 0;
  }
  .spotlight-chromeless-btn:hover {
    opacity: 1;
  }
</style>
