<script lang="ts">
  import type { MountEntry } from '../../services/api'
  import { getMountFilePath } from '../../services/api'
  import {
    AUDIO_EXTS,
    IMAGE_EXTS,
    TEXT_EXTS,
    VIDEO_EXTS,
    mountPathExt,
  } from '../../utils/mountFileTypes'

  type MediaStripProps = {
    entries?: readonly MountEntry[]
    selectedIndex?: number
    currentDir?: string
    compact?: boolean
    getDataUrl?: (name: string) => string | undefined
    savedNames?: ReadonlySet<string>
    /** Appends a trailing "load more results" tile, e.g. for a paginated search strip. */
    hasMore?: boolean
    loadingMore?: boolean
    onSelect?: (index: number) => void
    onNavigate?: (name: string) => void
    onPreview?: (index: number) => void
    onLoadMore?: () => void
  }

  let {
    entries = [],
    selectedIndex = -1,
    currentDir = '',
    compact = false,
    getDataUrl,
    savedNames,
    hasMore = false,
    loadingMore = false,
    onSelect,
    onNavigate,
    onPreview,
    onLoadMore,
  }: MediaStripProps = $props()

  function isImage(entry: MountEntry): boolean {
    return !entry.is_dir && IMAGE_EXTS.has(mountPathExt(entry.name))
  }

  function isAudio(entry: MountEntry): boolean {
    return !entry.is_dir && AUDIO_EXTS.has(mountPathExt(entry.name))
  }

  function isVideo(entry: MountEntry): boolean {
    return !entry.is_dir && VIDEO_EXTS.has(mountPathExt(entry.name))
  }

  function isText(entry: MountEntry): boolean {
    return !entry.is_dir && TEXT_EXTS.has(mountPathExt(entry.name))
  }

  function isIconTile(entry: MountEntry): boolean {
    if (entry.placeholder || entry.is_dir) return true
    return !isImage(entry)
  }

  function filePath(name: string): string {
    return currentDir ? `${currentDir}/${name}` : name
  }


  function handleClick(i: number, entry: MountEntry) {
    if (entry.placeholder) return
    if (entry.is_dir) {
      onNavigate?.(entry.name)
    } else {
      if (isMobile()) {
        onSelect?.(i)
        onPreview?.(i)
      } else {
        onSelect?.(i)
      }
    }
  }

  function handleDblClick(i: number, entry: MountEntry) {
    if (entry.placeholder || entry.is_dir) return
    onPreview?.(i)
  }

  function nextSelectableIndex(from: number, delta: number): number {
    let j = from + delta
    while (j >= 0 && j < entries.length && entries[j]?.placeholder) {
      j += delta
    }
    if (j < 0 || j >= entries.length) {
      return from
    }
    return j
  }

  let firstFocusableIndex = $derived.by(() => {
    const i = entries.findIndex((e) => !e.placeholder)
    return i >= 0 ? i : 0
  })

  function handleKeyDown(e: KeyboardEvent, i: number, entry: MountEntry) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (entry.placeholder) return
      if (entry.is_dir) {
        onNavigate?.(entry.name)
      } else {
        onSelect?.(i)
        onPreview?.(i)
      }
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      const next = nextSelectableIndex(i, 1)
      onSelect?.(next)
      focusTile(next)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      const prev = nextSelectableIndex(i, -1)
      onSelect?.(prev)
      focusTile(prev)
    }
  }

  let stripRoot: HTMLDivElement | null = null

  function focusTile(i: number) {
    const tile = stripRoot?.querySelector<HTMLElement>(`.carousel-tile[data-index="${i}"]`)
    tile?.focus()
  }

  function isMobile(): boolean {
    return window.matchMedia('(max-width: 600px)').matches
  }

  function handleImgError(e: Event) {
    const img = e.currentTarget as HTMLImageElement
    img.style.display = 'none'
  }
</script>

<div
  bind:this={stripRoot}
  class={['carousel-strip', compact && 'compact']}
  role="listbox"
  aria-label="Media files"
>
  {#each entries as entry, i (entry.name)}
    <div
      class={[
        'carousel-tile',
        isIconTile(entry) && 'tile-icon-only',
        i === selectedIndex && 'selected',
        savedNames?.has(entry.name) && 'tile-saved',
        entry.placeholder === true && 'tile-placeholder',
      ]}
      data-index={i}
      role="option"
      aria-selected={i === selectedIndex}
      aria-disabled={entry.placeholder === true}
      tabindex={entry.placeholder
        ? -1
        : i === selectedIndex || (selectedIndex === -1 && i === firstFocusableIndex)
          ? 0
          : -1}
      onclick={() => handleClick(i, entry)}
      ondblclick={() => handleDblClick(i, entry)}
      onkeydown={(e) => handleKeyDown(e, i, entry)}
    >
      {#if entry.placeholder === true}
        <div class="tile-placeholder-inner" aria-hidden="true"></div>
      {:else if entry.is_dir}
        <span class="tile-icon" aria-hidden="true">📁</span>
      {:else if isImage(entry)}
        <img
          src={getDataUrl?.(entry.name) ?? getMountFilePath(filePath(entry.name))}
          alt={entry.name}
          loading="lazy"
          onerror={handleImgError}
        />
      {:else if isVideo(entry)}
        <span class="tile-icon" aria-hidden="true">🎬</span>
      {:else if isAudio(entry)}
        <span class="tile-icon" aria-hidden="true">🎵</span>
      {:else if isText(entry)}
        <span class="tile-icon" aria-hidden="true">📝</span>
      {:else}
        <span class="tile-icon" aria-hidden="true">📄</span>
      {/if}
      {#if !isImage(entry)}
        <span class="tile-name">{entry.name}</span>
      {/if}
    </div>
  {/each}
  {#if entries.length === 0 && !hasMore}
    <span class="carousel-empty">Empty folder</span>
  {/if}
  {#if hasMore}
    <button
      type="button"
      class="carousel-tile tile-load-more"
      disabled={loadingMore}
      aria-label="Load more results"
      onclick={() => onLoadMore?.()}
    >
      <span class="tile-icon" aria-hidden="true">{loadingMore ? '…' : '+'}</span>
      <span class="tile-name">{loadingMore ? 'Loading' : 'Load more'}</span>
    </button>
  {/if}
</div>

<style>
  .carousel-tile.tile-placeholder {
    cursor: default;
    pointer-events: none;
    opacity: 0.85;
  }
  .tile-placeholder-inner {
    width: 100%;
    height: 100%;
    min-height: 4.5rem;
    border-radius: 4px;
    background: linear-gradient(
      110deg,
      var(--pico-muted-border-color, #444) 0%,
      var(--pico-card-background-color, #2a2a2a) 45%,
      var(--pico-muted-border-color, #444) 90%
    );
    background-size: 200% 100%;
    animation: media-strip-ph 1.2s ease-in-out infinite;
  }
  @keyframes media-strip-ph {
    0% {
      background-position: 100% 0;
    }
    100% {
      background-position: -100% 0;
    }
  }
  .carousel-tile.tile-saved {
    box-shadow: inset 0 0 0 2px var(--pico-primary, #3b88e6);
  }
  .tile-name {
    font-size: 0.7rem;
    word-break: break-all;
    line-height: 1.2;
    max-height: 2.4em;
    overflow: hidden;
    width: 100%;
    text-align: center;
  }
  .carousel-empty {
    opacity: 0.4;
    font-size: 0.85rem;
    padding: 1rem;
  }
  .tile-load-more {
    background: none;
    border: 2px solid var(--pico-muted-border-color);
    color: inherit;
    font: inherit;
  }
  .tile-load-more:disabled {
    opacity: 0.6;
    cursor: default;
  }
</style>
