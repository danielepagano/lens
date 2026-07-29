<script lang="ts">
  import { getMountFilePath } from '../../services/api'
  import {
    isMountAudioPath,
    isMountDirPath,
    isMountImagePath,
    isMountMarkdownPath,
    isMountPlainPrePath,
    isMountVideoPath,
  } from '../../utils/mountFileTypes'
  import SpotlightImageStage from './SpotlightImageStage.svelte'
  import SpotlightMediaBody from './SpotlightMediaBody.svelte'
  import MediaSpotlightActions from './MediaSpotlightActions.svelte'
  import {
    createPlainPreviewState,
    loadPlainPreview,
    resetPlainPreview,
    type PlainPreviewState,
  } from './plainPreview'
  import type { MediaSpotlightCallbacks, MediaSpotlightMode } from './mediaSpotlightTypes'

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
    onOpenMetadata?: () => void
  } & MediaSpotlightCallbacks

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
    onOpenMetadata,
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

  let isDir = $derived(isMountDirPath(path))
  let isAudio = $derived(path !== null && isMountAudioPath(path))
  let isImage = $derived(path !== null && !isDir && isMountImagePath(path))
  let isPlainPre = $derived(path !== null && isMountPlainPrePath(path))
  let isMarkdownPreview = $derived(path !== null && isMountMarkdownPath(path))
  let isVideo = $derived(path !== null && isMountVideoPath(path))
  let filename = $derived(path ? path.split('/').pop() ?? path : '')
  let pathToCopy = $derived(
    path !== null && !isDir ? (mode === 'preview' ? refCopyPath : path) : null,
  )
  let spotlightFill = $derived(isPlainPre || isMarkdownPreview || isVideo || isAudio)
  let imageSrc = $derived(previewSrc ?? (path ? getMountFilePath(path) : ''))
  let showInfoButton = $derived(path !== null && !isDir && !(chromeless && isImage))

  let plainPreview = $state.raw<PlainPreviewState>(createPlainPreviewState())

  $effect(() => {
    if (isPlainPre && path && path !== plainPreview.path) {
      void loadPlainPreview(plainPreview, path).then((next) => {
        plainPreview = next
      })
      return
    }
    if ((!isPlainPre || !path) && plainPreview.path !== null) {
      plainPreview = resetPlainPreview(plainPreview)
    }
  })

  function handleSpotlightCloseClick() {
    if (chromeless && isImage) onToggleChromeless?.()
    else onClose?.()
  }
</script>

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
      {#if isImage}
        <SpotlightImageStage
          {imageSrc}
          {filename}
          {chromeless}
          onToggleChromeless={onToggleChromeless}
        />
      {:else}
        <SpotlightMediaBody
          {path}
          {filename}
          {imageSrc}
          {isAudio}
          {isVideo}
          {isPlainPre}
          {isMarkdownPreview}
          {isDir}
          plainPreviewLoading={plainPreview.loading}
          plainPreviewError={plainPreview.error}
          plainPreviewText={plainPreview.text}
        />
      {/if}
      {#if showInfoButton}
        <button
          type="button"
          class="spotlight-info-btn"
          aria-label="Show metadata"
          onclick={() => onOpenMetadata?.()}
        >i</button>
      {/if}
    {/if}
  </div>

  <MediaSpotlightActions
    {path}
    {pathToCopy}
    {filename}
    {mode}
    {isDir}
    {saved}
    {saving}
    hasPreviewSrc={previewSrc !== null}
    {renaming}
    {renameValue}
    hidden={chromeless && isImage}
    {onAttach}
    {onDownload}
    {onStartRename}
    {onConfirmRename}
    {onCancelRename}
    {onDelete}
    {onSave}
  />
</div>

<style>
  .spotlight-root {
    display: contents;
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
  .spotlight-info-btn {
    position: absolute;
    bottom: 0.5rem;
    right: 0.5rem;
    background: rgba(0, 0, 0, 0.45);
    border: none;
    color: #fff;
    font-size: 0.85rem;
    font-style: italic;
    font-family: Georgia, 'Times New Roman', serif;
    font-weight: 700;
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
  .spotlight-info-btn:hover {
    opacity: 1;
  }
</style>
