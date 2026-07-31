<script lang="ts">
  import type { SearchMediaItem } from '../../services/api'
  import { getMountFilePath } from '../../services/api'
  import { AUDIO_EXTS, IMAGE_EXTS, TEXT_EXTS, VIDEO_EXTS, mountPathExt } from '../../utils/mountFileTypes'
  import { extraMetadataFields, formatMetadataValue } from './mediaSearchHandlers'

  type Props = {
    results?: readonly SearchMediaItem[]
    loading?: boolean
    loadingMore?: boolean
    error?: string | null
    hasMore?: boolean
    onSelect?: (index: number) => void
    onLoadMore?: () => void
  }

  let {
    results = [],
    loading = false,
    loadingMore = false,
    error = null,
    hasMore = false,
    onSelect = undefined,
    onLoadMore = undefined,
  }: Props = $props()

  function isImage(item: SearchMediaItem): boolean {
    return IMAGE_EXTS.has(mountPathExt(item.relative_path))
  }
  function isAudio(item: SearchMediaItem): boolean {
    return AUDIO_EXTS.has(mountPathExt(item.relative_path))
  }
  function isVideo(item: SearchMediaItem): boolean {
    return VIDEO_EXTS.has(mountPathExt(item.relative_path))
  }
  function isText(item: SearchMediaItem): boolean {
    return TEXT_EXTS.has(mountPathExt(item.relative_path))
  }

  function handleImgError(e: Event) {
    const img = e.currentTarget as HTMLImageElement
    img.style.display = 'none'
  }

  function handleRowKeydown(e: KeyboardEvent, i: number) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSelect?.(i)
    }
  }
</script>

<div class="search-results" role="listbox" aria-label="Search results">
  {#each results as item, i (item.relative_path)}
    <div
      class="search-result-row"
      role="option"
      aria-selected="false"
      tabindex="0"
      onclick={() => onSelect?.(i)}
      onkeydown={(e) => handleRowKeydown(e, i)}
    >
      <div class="search-result-thumb">
        {#if isImage(item)}
          <img src={getMountFilePath(item.relative_path)} alt="" loading="lazy" onerror={handleImgError} />
        {:else if isVideo(item)}
          <span class="search-result-icon" aria-hidden="true">🎬</span>
        {:else if isAudio(item)}
          <span class="search-result-icon" aria-hidden="true">🎵</span>
        {:else if isText(item)}
          <span class="search-result-icon" aria-hidden="true">📝</span>
        {:else}
          <span class="search-result-icon" aria-hidden="true">📄</span>
        {/if}
      </div>
      <div class="search-result-info">
        <div class="search-result-path">{item.relative_path}</div>
        {#each extraMetadataFields(item) as [key, value] (key)}
          <div class="search-result-field">
            <span class="search-result-field-key">{key}:</span>
            {formatMetadataValue(value)}
          </div>
        {/each}
      </div>
    </div>
  {/each}

  {#if loading}
    <div class="search-results-status">Searching…</div>
  {:else if error}
    <div class="search-results-status search-results-error" role="alert">{error}</div>
  {:else if results.length === 0}
    <div class="search-results-status">No results</div>
  {/if}

  {#if hasMore}
    <button
      type="button"
      class="search-load-more"
      disabled={loadingMore}
      onclick={() => onLoadMore?.()}
    >{loadingMore ? 'Loading…' : 'Load more results'}</button>
  {/if}
</div>

<style>
  .search-results {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem;
  }
  .search-result-row {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.4rem;
    border-radius: 6px;
    border: 2px solid transparent;
    cursor: pointer;
    text-align: left;
  }
  .search-result-row:hover,
  .search-result-row:focus-visible {
    border-color: var(--pico-primary);
    background: var(--pico-primary-background);
    outline: none;
  }
  .search-result-thumb {
    flex-shrink: 0;
    width: 76px;
    height: 76px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .search-result-thumb img {
    width: 76px;
    height: 76px;
    object-fit: scale-down;
    border-radius: 4px;
    display: block;
  }
  .search-result-icon {
    font-size: 2rem;
    opacity: 0.7;
  }
  .search-result-info {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }
  .search-result-path {
    font-size: 0.85rem;
    font-weight: 600;
    word-break: break-all;
  }
  .search-result-field {
    font-size: 0.75rem;
    opacity: 0.75;
    word-break: break-word;
  }
  .search-result-field-key {
    opacity: 0.8;
    font-weight: 600;
  }
  .search-results-status {
    padding: 1rem;
    text-align: center;
    opacity: 0.6;
    font-size: 0.85rem;
  }
  .search-results-error {
    color: var(--pico-del-color, #e05c5c);
    opacity: 1;
    white-space: pre-wrap;
  }
  .search-load-more {
    align-self: center;
    margin-top: 0.25rem;
    font-size: 0.85rem;
  }
</style>
