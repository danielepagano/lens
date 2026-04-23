<script lang="ts">
  import { createEventDispatcher } from 'svelte'
  import type { MountEntry } from '../../services/api'
  import { getMountFilePath } from '../../services/api'

  export let entries: MountEntry[] = []
  export let selectedIndex: number = -1
  export let currentDir: string = ''

  const dispatch = createEventDispatcher<{
    select: number
    navigate: string
    preview: number
  }>()

  const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])

  function ext(name: string): string {
    const dot = name.lastIndexOf('.')
    return dot >= 0 ? name.slice(dot).toLowerCase() : ''
  }

  function isImage(entry: MountEntry): boolean {
    return !entry.is_dir && IMAGE_EXTS.has(ext(entry.name))
  }

  function filePath(name: string): string {
    return currentDir ? `${currentDir}/${name}` : name
  }

  function handleClick(i: number, entry: MountEntry) {
    if (entry.is_dir) {
      dispatch('navigate', entry.name)
    } else {
      if (isMobile()) {
        dispatch('select', i)
        dispatch('preview', i)
      } else {
        dispatch('select', i)
      }
    }
  }

  function handleDblClick(i: number, entry: MountEntry) {
    if (!entry.is_dir) {
      dispatch('preview', i)
    }
  }

  function handleKeyDown(e: KeyboardEvent, i: number, entry: MountEntry) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      if (entry.is_dir) {
        dispatch('navigate', entry.name)
      } else {
        dispatch('select', i)
        dispatch('preview', i)
      }
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      const next = Math.min(i + 1, entries.length - 1)
      dispatch('select', next)
      focusTile(next)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      const prev = Math.max(i - 1, 0)
      dispatch('select', prev)
      focusTile(prev)
    }
  }

  function focusTile(i: number) {
    const tile = document.querySelector<HTMLElement>(`.carousel-tile[data-index="${i}"]`)
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

<div class="carousel-strip" role="listbox" aria-label="Media files">
  {#each entries as entry, i (entry.name)}
    <div
      class="carousel-tile"
      class:selected={i === selectedIndex}
      data-index={i}
      role="option"
      aria-selected={i === selectedIndex}
      tabindex={i === selectedIndex || (selectedIndex === -1 && i === 0) ? 0 : -1}
      on:click={() => handleClick(i, entry)}
      on:dblclick={() => handleDblClick(i, entry)}
      on:keydown={(e) => handleKeyDown(e, i, entry)}
    >
      {#if entry.is_dir}
        <span class="tile-icon" aria-hidden="true">📁</span>
      {:else if isImage(entry)}
        <img
          src={getMountFilePath(filePath(entry.name))}
          alt={entry.name}
          loading="lazy"
          on:error={handleImgError}
        />
      {:else}
        <span class="tile-icon" aria-hidden="true">📄</span>
      {/if}
      <span class="tile-name">{entry.name}</span>
    </div>
  {/each}
  {#if entries.length === 0}
    <span class="carousel-empty">Empty folder</span>
  {/if}
</div>

<style>
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
</style>
