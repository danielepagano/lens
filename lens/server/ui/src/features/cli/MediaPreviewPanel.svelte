<script lang="ts">
  import { mediaPreviewRequest } from '../../stores/ui'

  const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
  const VIDEO_EXTS = ['.mp4', '.webm', '.mov', '.avi']
  const PREVIEW_EXTS = ['.md', '.txt']

  let dialog: HTMLDialogElement | undefined

  $: path = $mediaPreviewRequest?.path ?? ''
  $: ext = path.includes('.') ? '.' + path.split('.').pop()!.toLowerCase() : ''
  $: mediaKind = IMAGE_EXTS.includes(ext)
    ? 'image'
    : VIDEO_EXTS.includes(ext)
      ? 'video'
      : PREVIEW_EXTS.includes(ext)
        ? 'preview'
        : 'file'
  $: src =
    mediaKind === 'preview'
      ? `/mount/preview/${path.replace(/^\//, '')}`
      : `/mount/file/${path.replace(/^\//, '')}`

  $: if ($mediaPreviewRequest) {
    dialog?.showModal()
  } else {
    dialog?.close()
  }

  function handleClose() {
    mediaPreviewRequest.set(null)
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-noninteractive-element-interactions -->
<dialog
  bind:this={dialog}
  class="media-preview-dialog"
  on:close={handleClose}
  on:click={handleBackdropClick}
>
  {#if path}
    <div class="media-preview-content">
      <button type="button" class="media-preview-close" on:click={handleClose}>✕</button>

      {#if mediaKind === 'image'}
        <img {src} alt={path.split('/').pop() ?? path} class="media-preview-img" />
      {:else if mediaKind === 'video'}
        <video {src} controls class="media-preview-video">
          <track kind="captions" />
        </video>
      {:else}
        <iframe {src} title={path.split('/').pop() ?? path} class="media-preview-iframe"></iframe>
      {/if}
    </div>
  {/if}
</dialog>

<style>
  .media-preview-dialog {
    border: none;
    background: transparent;
    padding: 0;
    margin: 0;
    width: 100vw;
    height: 100vh;
    max-width: 100vw;
    max-height: 100vh;
  }

  .media-preview-dialog::backdrop {
    background: rgba(0, 0, 0, 0.85);
  }

  .media-preview-content {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    position: relative;
  }

  .media-preview-close {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    z-index: 10;
    background: rgba(0, 0, 0, 0.5);
    color: #fff;
    border: none;
    border-radius: 50%;
    width: 36px;
    height: 36px;
    font-size: 1.1rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }

  .media-preview-close:hover {
    background: rgba(0, 0, 0, 0.8);
  }

  .media-preview-img {
    max-width: 90vw;
    max-height: 90vh;
    object-fit: contain;
  }

  .media-preview-video {
    max-width: 90vw;
    max-height: 90vh;
  }

  .media-preview-iframe {
    width: 80vw;
    height: 85vh;
    border: none;
    background: #fff;
    border-radius: 4px;
  }
</style>
