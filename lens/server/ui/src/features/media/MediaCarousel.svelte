<script lang="ts">
  import type { MediaCarouselRequest } from '../../stores/ui'
  import { mediaCarouselRequest } from '../../stores/ui'
  import { browseMountDir, type MountEntry } from '../../services/api'
  import { isMountImagePath } from '../../utils/mountFileTypes'
  import MediaSpotlight from './MediaSpotlight.svelte'
  import MediaCarouselHeader from './MediaCarouselHeader.svelte'
  import MediaCarouselStripToolbar from './MediaCarouselStripToolbar.svelte'
  import {
    attachFromCarousel,
    confirmRenameInCarousel,
    deleteFromCarousel,
    downloadFromCarousel,
    removeFromScene,
    uploadToCarousel,
    type MediaCarouselHandlerCtx,
  } from './mediaCarouselHandlers'

  type MediaCarouselProps = {
    onDone?: () => void
  }

  let { onDone }: MediaCarouselProps = $props()

  let currentDir = $state('')
  let entries = $state.raw<MountEntry[]>([])
  let selectedIndex = $state(-1)
  let loading = $state(false)
  let error = $state<string | null>(null)
  let renaming = $state(false)
  let renameValue = $state('')
  let uploading = $state(false)
  let removing = $state(false)
  let dragActive = $state(false)
  let uploadInput = $state<HTMLInputElement | null>(null)

  let request = $derived($mediaCarouselRequest)
  let mode = $derived(request?.mode ?? 'manage')
  let title = $derived(
    mode === 'attach' ? 'Attach Media' : mode === 'replace' ? 'Replace Media' : 'Manage Media',
  )

  let lastRequest: MediaCarouselRequest | null = null
  $effect(() => {
    if (request === null) {
      lastRequest = null
      return
    }
    if (request !== lastRequest) {
      lastRequest = request
      void open(request.dir)
    }
  })

  async function open(dir: string) {
    currentDir = dir
    selectedIndex = -1
    renaming = false
    error = null
    await loadDir()
  }

  async function loadDir() {
    loading = true
    error = null
    try {
      entries = await browseMountDir(currentDir)
    } catch (e) {
      error = e instanceof Error ? e.message : String(e)
      entries = []
    } finally {
      loading = false
    }
  }

  function close() {
    mediaCarouselRequest.set(null)
    renaming = false
  }

  let breadcrumbs = $derived.by(() =>
    currentDir
      ? currentDir.split('/').filter(Boolean).map((seg, i, arr) => ({
          label: seg,
          path: arr.slice(0, i + 1).join('/'),
        }))
      : [],
  )

  async function navigateTo(dir: string) {
    currentDir = dir
    selectedIndex = -1
    renaming = false
    await loadDir()
  }

  let selectedEntry = $derived(selectedIndex >= 0 ? entries[selectedIndex] ?? null : null)
  let selectedPath = $derived(
    selectedEntry && !selectedEntry.is_dir
      ? (currentDir ? `${currentDir}/${selectedEntry.name}` : selectedEntry.name)
      : null,
  )
  let selectedIsImage = $derived(!!(selectedPath && isMountImagePath(selectedPath)))

  let imageChromeless = $state(false)
  let prevSpotlightPath: string | null = null
  $effect(() => {
    if (selectedPath !== prevSpotlightPath) {
      prevSpotlightPath = selectedPath
      imageChromeless = false
    }
  })

  function handlerCtx(): MediaCarouselHandlerCtx {
    return {
      getRequest: () => request,
      getSelectedPath: () => selectedPath,
      getCurrentDir: () => currentDir,
      getEntries: () => entries,
      setError: (message) => {
        error = message
      },
      setRenaming: (value) => {
        renaming = value
      },
      setSelectedIndex: (index) => {
        selectedIndex = index
      },
      setRemoving: (value) => {
        removing = value
      },
      setUploading: (value) => {
        uploading = value
      },
      close,
      onDone,
      loadDir,
      navigateTo,
    }
  }

  function handleStartRename() {
    if (!selectedPath) return
    renameValue = selectedPath
    renaming = true
  }
</script>

{#if request !== null}
  <div
    class={[
      'carousel-overlay',
      imageChromeless && 'carousel-image-only',
      dragActive && 'carousel-drop-active',
    ]}
    ondragover={(e) => {
      e.preventDefault()
      dragActive = true
    }}
    ondragleave={(e) => {
      if ((e.currentTarget as Element).contains(e.relatedTarget as Node)) return
      dragActive = false
    }}
    ondrop={(e) => {
      e.preventDefault()
      dragActive = false
      const file = e.dataTransfer?.files?.[0]
      if (file) void uploadToCarousel(handlerCtx(), file)
    }}
    role="dialog"
    tabindex="-1"
    aria-modal="true"
    aria-label={title}
  >
    <MediaCarouselHeader {title} {breadcrumbs} onClose={close} onNavigate={navigateTo} />

    <div class="carousel-body">
      {#if loading}
        <div class="carousel-loading">Loading…</div>
      {:else}
        <MediaCarouselStripToolbar
          {entries}
          {selectedIndex}
          {currentDir}
          {selectedPath}
          showClearScene={
            mode === 'replace' &&
            request.attachAddress !== undefined &&
            request.replaceImageLine !== undefined
          }
          {uploading}
          {removing}
          bind:uploadInput
          onSelect={(index) => {
            selectedIndex = index
            renaming = false
          }}
          onNavigate={(name) => void navigateTo(currentDir ? `${currentDir}/${name}` : name)}
          onPreview={(index) => {
            selectedIndex = index
          }}
          onClearScene={() => void removeFromScene(handlerCtx())}
          onUploadClick={() => uploadInput?.click()}
          onUploadChange={(e) => {
            const file = (e.currentTarget as HTMLInputElement).files?.[0]
            if (!file) return
            void uploadToCarousel(handlerCtx(), file)
            ;(e.currentTarget as HTMLInputElement).value = ''
          }}
        />
      {/if}

      {#if selectedPath !== null}
        <MediaSpotlight
          path={selectedPath}
          mode={mode === 'replace' ? 'replace' : mode}
          {renaming}
          {renameValue}
          chromeless={imageChromeless}
          onAttach={() => void attachFromCarousel(handlerCtx())}
          onDownload={() => downloadFromCarousel(handlerCtx())}
          onStartRename={handleStartRename}
          onConfirmRename={(value) => void confirmRenameInCarousel(handlerCtx(), value)}
          onCancelRename={() => {
            renaming = false
          }}
          onDelete={() => void deleteFromCarousel(handlerCtx())}
          onClose={() => {
            selectedIndex = -1
          }}
          onToggleChromeless={() => {
            if (selectedIsImage) imageChromeless = !imageChromeless
          }}
        />
      {/if}

      {#if uploading}
        <div class="carousel-uploading">Uploading…</div>
      {/if}
      {#if removing}
        <div class="carousel-uploading">Removing…</div>
      {/if}
      {#if error}
        <div class="carousel-error" role="alert">{error}</div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .carousel-loading,
  .carousel-uploading {
    padding: 1rem;
    opacity: 0.6;
    font-size: 0.85rem;
  }
  .carousel-error {
    padding: 0.5rem 0.9rem;
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.85rem;
    flex-shrink: 0;
  }
</style>
