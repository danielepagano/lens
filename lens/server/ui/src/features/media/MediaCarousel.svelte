<script lang="ts">
  import type { MediaCarouselRequest } from '../../stores/ui'
  import { mediaCarouselRequest } from '../../stores/ui'
  import { currentProject } from '../../stores/project'
  import { browseMountDir, type MountEntry } from '../../services/api'
  import { isMountImagePath } from '../../utils/mountFileTypes'
  import MediaSpotlight from './MediaSpotlight.svelte'
  import MediaCarouselHeader from './MediaCarouselHeader.svelte'
  import MediaCarouselStripToolbar from './MediaCarouselStripToolbar.svelte'
  import MediaSearchBar from './MediaSearchBar.svelte'
  import MediaSearchResultsList from './MediaSearchResultsList.svelte'
  import MediaStrip from './MediaStrip.svelte'
  import MediaMetadataPanel from './MediaMetadataPanel.svelte'
  import { dirnameOfPath, requiredKeywordsForDir } from './mediaSearchHandlers'
  import { MediaSearchState } from './mediaSearchState.svelte'
  import {
    attachFromCarousel,
    chromakeyFromCarousel,
    confirmRenameInCarousel,
    deleteFromCarousel,
    downloadFromCarousel,
    removeFromScene,
    uploadToCarousel,
    type MediaCarouselHandlerCtx,
    type PendingLayer,
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
  let pendingDeleteConfirm = $state(false)
  let pendingLayer = $state<PendingLayer | null>(null)

  // Search mode. See MediaSearchState for the remembered-until-reload /
  // cleared-on-project-switch lifecycle (#103).
  const search = new MediaSearchState()

  function openSearch() {
    // Opening the search bar changes nothing else — the current folder
    // grid (and whatever's selected in it) stays exactly as it was. The
    // content pane only switches to search results once a search actually
    // runs (see `showingSearchContent`).
    // Search box is empty (nothing typed, nothing remembered) and we're in
    // a subfolder: pre-fill required terms for the folder path, so
    // pressing Enter reproduces roughly the same files, and typing more
    // just narrows further instead of starting from scratch. Gated on
    // emptiness alone, not on whether a search has run before — a
    // previously-searched-then-cleared box should default the same way.
    if (!search.query.trim() && currentDir) {
      search.query = requiredKeywordsForDir(currentDir)
    }
    search.open = true
  }

  function closeSearch() {
    // Only clear the selection if it pointed into search results — a
    // browse-mode selection made while the (unused) search bar was open
    // should survive closing it.
    if (showingSearchContent) selectedIndex = -1
    search.open = false
  }

  // Switching projects points the mount at a different backend entirely —
  // a remembered query/results/browse listing from the old project is not
  // just stale, every path in it 404s. This component is a persistent
  // singleton (see App.svelte) so nothing else would ever clear it out.
  let lastProject: string | null | undefined = undefined
  $effect(() => {
    const project = $currentProject
    if (lastProject !== undefined && project !== lastProject) {
      mediaCarouselRequest.set(null)
      search.resetForProjectSwitch()
      currentDir = ''
      entries = []
      selectedIndex = -1
    }
    lastProject = project
  })

  let request = $derived($mediaCarouselRequest)
  let mode = $derived(request?.mode ?? 'manage')
  let title = $derived(
    pendingLayer
      ? `Pick the ${pendingLayer.role === 'background' ? 'foreground' : 'background'} layer`
      : mode === 'attach'
        ? 'Attach Media'
        : mode === 'replace'
          ? 'Replace Media'
          : mode === 'chromakey'
            ? 'Chromakey Source'
            : 'Manage Media',
  )

  let lastRequest: MediaCarouselRequest | null = null
  $effect(() => {
    if (request === null) {
      lastRequest = null
      return
    }
    if (request !== lastRequest) {
      lastRequest = request
      pendingLayer = null
      void open(request)
    }
  })

  async function open(req: MediaCarouselRequest) {
    currentDir = req.dir
    selectedIndex = -1
    renaming = false
    error = null
    pendingDeleteConfirm = false
    search.open = false
    await loadDir()
    if (req.searchQuery !== undefined) {
      search.query = req.searchQuery
      openSearch()
      void search.performSearch(search.query, 1)
    }
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
    // Keep search results in sync with browse-mode mutations (upload, delete,
    // rename) that route through this same function.
    if (search.open && search.query.trim()) {
      await search.performSearch(search.query, 1)
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
    pendingDeleteConfirm = false
    await loadDir()
  }

  // The content pane only switches from the folder grid to search results
  // once a search has actually run — merely opening the search bar (#103
  // follow-up) must not touch what's currently on screen.
  let showingSearchContent = $derived(search.open && search.hasRun)

  let selectedEntry = $derived(
    !showingSearchContent && selectedIndex >= 0 ? entries[selectedIndex] ?? null : null,
  )
  let selectedSearchItem = $derived(
    showingSearchContent && selectedIndex >= 0 ? search.results[selectedIndex] ?? null : null,
  )
  let selectedPath = $derived(
    selectedSearchItem
      ? selectedSearchItem.relative_path
      : selectedEntry && !selectedEntry.is_dir
        ? (currentDir ? `${currentDir}/${selectedEntry.name}` : selectedEntry.name)
        : null,
  )
  let selectedIsImage = $derived(!!(selectedPath && isMountImagePath(selectedPath)))

  let imageChromeless = $state(false)
  let metadataOpen = $state(false)
  let prevSpotlightPath: string | null = null
  $effect(() => {
    if (selectedPath !== prevSpotlightPath) {
      prevSpotlightPath = selectedPath
      imageChromeless = false
      metadataOpen = false
    }
  })

  function handlerCtx(): MediaCarouselHandlerCtx {
    return {
      getRequest: () => request,
      getSelectedPath: () => selectedPath,
      getCurrentDir: () => (showingSearchContent && selectedPath ? dirnameOfPath(selectedPath) : currentDir),
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
      getPendingDeleteConfirm: () => pendingDeleteConfirm,
      setPendingDeleteConfirm: (value) => {
        pendingDeleteConfirm = value
      },
      getPendingLayer: () => pendingLayer,
      setPendingLayer: (value) => {
        pendingLayer = value
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
    <MediaCarouselHeader
      {title}
      {breadcrumbs}
      showPath={!showingSearchContent}
      onClose={close}
      onNavigate={navigateTo}
    />

    <div class="carousel-body">
      {#if pendingLayer}
        <div class="carousel-pairing-banner">
          <span>Pairing with <strong>{pendingLayer.path.split('/').pop()}</strong> ({pendingLayer.role})</span>
          <button type="button" onclick={() => (pendingLayer = null)}>Cancel</button>
        </div>
      {/if}
      {#if loading}
        <div class="carousel-loading">Loading…</div>
      {:else if showingSearchContent}
        {#if selectedPath === null}
          <MediaSearchResultsList
            results={search.results}
            loading={search.loading}
            loadingMore={search.loadingMore}
            error={search.error}
            hasMore={search.hasMore}
            onSelect={(index) => {
              selectedIndex = index
              renaming = false
              pendingDeleteConfirm = false
            }}
            onLoadMore={() => search.loadMore()}
          />
        {:else}
          <div class="carousel-strip-wrap" style="flex: 0 0 auto">
            <MediaStrip
              entries={search.results.map((r) => ({ name: r.relative_path, is_dir: false }))}
              {selectedIndex}
              currentDir=""
              compact={true}
              hasMore={search.hasMore}
              loadingMore={search.loadingMore}
              onSelect={(index) => {
                selectedIndex = index
              }}
              onPreview={(index) => {
                selectedIndex = index
              }}
              onLoadMore={() => search.loadMore()}
            />
          </div>
        {/if}
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
            pendingDeleteConfirm = false
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
          onOpenSearch={openSearch}
          searchOpen={search.open}
        />
      {/if}

      {#if selectedPath !== null}
        <MediaSpotlight
          path={selectedPath}
          mode={mode === 'replace' ? 'replace' : mode}
          {renaming}
          {renameValue}
          chromeless={imageChromeless}
          onOpenMetadata={() => {
            metadataOpen = true
          }}
          onAttach={() =>
            mode === 'chromakey'
              ? chromakeyFromCarousel(handlerCtx())
              : void attachFromCarousel(handlerCtx())}
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

      {#if search.open && selectedPath === null}
        <MediaSearchBar
          bind:input={search.query}
          onSearch={(query) => search.run(query)}
          onClear={() => search.clear()}
          onClose={closeSearch}
        />
      {/if}

      <MediaMetadataPanel
        path={selectedPath}
        open={metadataOpen}
        onClose={() => {
          metadataOpen = false
        }}
      />

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
  .carousel-pairing-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.5rem 0.9rem;
    font-size: 0.85rem;
    background: var(--pico-mark-background-color, rgba(255, 200, 0, 0.15));
    flex-shrink: 0;
  }
  .carousel-pairing-banner button {
    flex-shrink: 0;
    font-size: 0.75rem !important;
    padding: 0.2rem 0.5rem !important;
    min-height: 28px !important;
  }
</style>
