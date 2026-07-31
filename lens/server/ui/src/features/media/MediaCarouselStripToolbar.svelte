<script lang="ts">
  import type { MountEntry } from '../../services/api'
  import MediaStrip from './MediaStrip.svelte'

  type Props = {
    entries?: readonly MountEntry[]
    selectedIndex?: number
    currentDir?: string
    selectedPath?: string | null
    showClearScene?: boolean
    uploading?: boolean
    removing?: boolean
    uploadInput?: HTMLInputElement | null
    onSelect?: (index: number) => void
    onNavigate?: (name: string) => void
    onPreview?: (index: number) => void
    onClearScene?: () => void
    onUploadClick?: () => void
    onUploadChange?: (event: Event) => void
    onOpenSearch?: () => void
    /** Hides the floating search button once the search bar itself is open (it has its own close button). */
    searchOpen?: boolean
  }

  let {
    entries = [],
    selectedIndex = -1,
    currentDir = '',
    selectedPath = null,
    showClearScene = false,
    uploading = false,
    removing = false,
    uploadInput = $bindable(null),
    onSelect = undefined,
    onNavigate = undefined,
    onPreview = undefined,
    onClearScene = undefined,
    onUploadClick = undefined,
    onUploadChange = undefined,
    onOpenSearch = undefined,
    searchOpen = false,
  }: Props = $props()
</script>

<div
  class="carousel-strip-wrap"
  style="flex: {selectedPath !== null ? '0 0 auto' : '1 1 auto'}"
>
  <MediaStrip
    {entries}
    {selectedIndex}
    {currentDir}
    compact={selectedPath !== null}
    onSelect={onSelect}
    onNavigate={onNavigate}
    onPreview={onPreview}
  />

  {#if selectedPath === null}
    {#if showClearScene}
      <button
        type="button"
        class="carousel-remove-scene-btn"
        aria-label="Clear media from passage"
        title="Clear scene image from this passage (does not delete the mount file)"
        disabled={uploading || removing}
        onclick={() => onClearScene?.()}
      >Clear Media</button>
    {/if}
    {#if !searchOpen}
      <button
        type="button"
        class={['carousel-search-btn', showClearScene && 'stacked']}
        aria-label="Search media"
        title="Search media"
        disabled={uploading || removing}
        onclick={() => onOpenSearch?.()}
      >🔍</button>
    {/if}
    <button
      type="button"
      class="carousel-upload-btn"
      aria-label="Upload file"
      title="Upload file"
      disabled={uploading || removing}
      onclick={() => onUploadClick?.()}
    >+</button>
    <input
      bind:this={uploadInput}
      type="file"
      class="sr-only"
      onchange={onUploadChange}
    />
  {/if}
</div>

<style>
  .carousel-strip-wrap {
    position: relative;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
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
  .carousel-search-btn {
    position: absolute;
    left: 0.65rem;
    bottom: 0.65rem;
    width: 40px;
    height: 40px;
    border-radius: 999px;
    border: 1px solid var(--pico-muted-border-color);
    background: var(--pico-card-background-color);
    font-size: 1.1rem;
    line-height: 1;
    padding: 0;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
    z-index: 5;
  }
  .carousel-search-btn.stacked {
    bottom: 3.35rem;
  }
  .carousel-search-btn:hover:not(:disabled) {
    filter: brightness(1.05);
  }
  .carousel-search-btn:active:not(:disabled) {
    transform: translateY(1px);
  }
  .carousel-search-btn:disabled {
    opacity: 0.55;
    cursor: default;
  }
  .carousel-search-btn:focus-visible {
    outline: 2px solid var(--pico-primary);
    outline-offset: 2px;
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
  .carousel-upload-btn:hover {
    filter: brightness(1.05);
  }
  .carousel-upload-btn:active {
    transform: translateY(1px);
  }
  .carousel-upload-btn:disabled {
    opacity: 0.55;
    cursor: default;
  }
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
