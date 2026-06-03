<script lang="ts">
  import { copyTextToClipboard } from '../../utils/copyToClipboard'
  import {
    appendFinalExt,
    finalSegmentExt,
    selectBasename,
    stripFinalExt,
  } from '../../utils/mountFileTypes'
  import type { MediaSpotlightCallbacks, MediaSpotlightMode } from './mediaSpotlightTypes'

  type Props = {
    path?: string | null
    pathToCopy?: string | null
    filename?: string
    mode?: MediaSpotlightMode
    isDir?: boolean
    saved?: boolean
    saving?: boolean
    hasPreviewSrc?: boolean
    renaming?: boolean
    renameValue?: string
    hidden?: boolean
  } & MediaSpotlightCallbacks

  let {
    path = null,
    pathToCopy = null,
    filename = '',
    mode = 'manage',
    isDir = false,
    saved = false,
    saving = false,
    hasPreviewSrc = false,
    renaming = false,
    renameValue = '',
    hidden = false,
    onAttach,
    onDownload,
    onStartRename,
    onConfirmRename,
    onCancelRename,
    onDelete,
    onSave,
  }: Props = $props()

  let confirmDelete = $state(false)
  let renameInput = $state<HTMLInputElement | null>(null)
  let renameDraft = $state('')
  let renameExtension = $state('')
  let renameFocusKey: string | null = null

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
    } else confirmDelete = true
  }

  function handleDeleteBlur() {
    confirmDelete = false
  }

  function handleCopyMountPath() {
    if (pathToCopy) void copyTextToClipboard(pathToCopy)
  }
</script>

{#if !hidden}
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
        disabled={saving || saved || !hasPreviewSrc}
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

{#if renaming && !hidden}
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

<style>
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
</style>
