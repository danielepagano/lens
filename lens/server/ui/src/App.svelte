<script lang="ts">
  import { onMount } from 'svelte'
  import { get } from 'svelte/store'
  import MainLayout from './layout/MainLayout.svelte'
  import TopBar from './layout/TopBar.svelte'
  import Cli from './features/cli/Cli.svelte'
  import TreeBrowser from './features/tree/TreeBrowser.svelte'
  import MarkdownView from './features/viewer/MarkdownView.svelte'
  import CliOutputPanel from './features/cli/CliOutputPanel.svelte'
  import TransactionResultPanel from './features/transaction/TransactionResultPanel.svelte'
  import StreamingPreviewPanel from './features/streaming/StreamingPreviewPanel.svelte'
  import MediaCarousel from './features/media/MediaCarousel.svelte'
  import MediaPreviewCarousel from './features/media/MediaPreviewCarousel.svelte'
  import KbDiffModal from './features/kb/KbDiffModal.svelte'
  import KbPanel from './features/kb/KbPanel.svelte'
  import InlineEditView from './features/editor/InlineEditView.svelte'
  import VisualNovelView from './features/visualNovel/VisualNovelView.svelte'
  import { getStats, getNode, getProjects, getPlayback, onAfterMutation } from './services/api'
  import { currentAddress, nodeContent } from './stores/document'
  import { applyStats, stats } from './stores/stats'
  import { kbPanelOpen, selectedKbId, kbFilters, inlineEditMode, editorFocused, treeRefreshTrigger } from './stores/ui'
  import { currentProject, availableProjects } from './stores/project'
  import { syncUrlHashFromWindow } from './stores/urlHash'
  import { parsedHash } from './stores/parsedHash'
  import { hashAfterNodeResolved } from './utils/appHash'
  import { vnCursorCliSlotEligible, playbackTailTextId } from './utils/vnCursorCli'
  import { playbackIndexToLogicalStep, vnLogicalStepCount } from './utils/vnPlaybackNav'
  import { setVisualNovelHash, resolveVisualNovelTtsSettings } from './utils/vnNavigate'
  import {
    vnModeFromParsed,
    vnImageExplore,
    vnPlayback,
    vnPlaybackItemCount,
    vnCursorCliOpSnapshot,
    vnError,
    vnPlaybackRefreshTrigger,
  } from './stores/visualNovel'

  $effect(() => {
    document.body.classList.toggle('editor-focused', $editorFocused)
  })

  const vnActive = $derived(
    vnModeFromParsed($parsedHash, $currentProject, $currentAddress),
  )

  $effect(() => {
    if (!vnActive) {
      vnPlayback.set(null)
      vnPlaybackItemCount.set(0)
      vnError.set(null)
      vnImageExplore.set(false)
    }
  })

  function hashKbParam(): string | null {
    return get(kbPanelOpen) ? get(selectedKbId) : null
  }

  interface ParsedHash {
    project: string | null
    path: string
    kb: string | null
  }

  function parseHash(hash: string): ParsedHash {
    if (!hash || hash === '#') return { project: null, path: '', kb: null }
    const raw = decodeURIComponent(hash.slice(1))
    const qIndex = raw.indexOf('?')
    const fullPath = qIndex === -1 ? raw : raw.slice(0, qIndex)
    const kb = qIndex === -1 ? null : new URLSearchParams(raw.slice(qIndex + 1)).get('kb')
    const stripped = fullPath.startsWith('/') ? fullPath.slice(1) : fullPath
    const slashIdx = stripped.indexOf('/')
    if (slashIdx === -1) return { project: stripped || null, path: '', kb }
    return { project: stripped.slice(0, slashIdx), path: stripped.slice(slashIdx + 1), kb }
  }

  function buildHash(path: string, kb: string | null): string {
    const slug = get(currentProject) ?? ''
    const base = path ? `${slug}/${path}` : slug
    return kb ? `${base}?kb=${encodeURIComponent(kb)}` : base
  }

  function _updateUrlKb(kb: string | null) {
    const currentPath = get(currentAddress) || ''
    const newHash = buildHash(currentPath, kb)
    if (window.location.hash.slice(1) !== newHash) {
      window.location.hash = newHash
    }
  }

  async function navigate(addr: string): Promise<void> {
    if (!addr) return
    try {
      inlineEditMode.set(null)
      const data = await getNode(addr)
      currentAddress.set(data.address)
      nodeContent.set(data.content)
      window.location.hash = buildHash(data.address, hashKbParam())
    } catch (e) {
      console.error('Navigation failed:', e)
    }
  }

  function syncLocation(addr: string): void {
    if (!addr) return
    inlineEditMode.set(null)
    window.location.hash = buildHash(addr, hashKbParam())
  }

  async function switchProject(slug: string): Promise<void> {
    currentProject.set(slug)
    currentAddress.set(null)
    nodeContent.set('')
    kbPanelOpen.set(false)
    selectedKbId.set(null)
    treeRefreshTrigger.update(n => n + 1)
    const newStats = await getStats()
    applyStats(newStats)
    await navigate(newStats.cursor || '')
  }

  async function handleCarouselDone(): Promise<void> {
    const addr = get(currentAddress)
    if (!addr) return
    if (vnModeFromParsed(get(parsedHash), get(currentProject), addr)) {
      vnPlaybackRefreshTrigger.update((n) => n + 1)
    }
    try {
      const data = await getNode(addr)
      nodeContent.set(data.content)
    } catch (e) {
      console.error('Carousel done refresh failed:', e)
    }
  }

  async function handleCliDone(): Promise<void> {
    const snap = get(vnCursorCliOpSnapshot)
    vnCursorCliOpSnapshot.set(null)
    const prevCursor = get(stats)?.cursor ?? null
    const addr = get(currentAddress)
    try {
      const newStats = await getStats()
      applyStats(newStats)
      const newCursor = newStats.cursor ?? null
      if (addr) {
        try {
          const data = await getNode(addr)
          nodeContent.set(data.content)
        } catch {
          // Node was deleted (e.g. rollback after cancel) — go to cursor.
          if (newCursor) await navigate(newCursor)
          return
        }
      }
      if (prevCursor === addr && newCursor !== prevCursor && newCursor) {
        navigate(newCursor)
      }

      if (
        snap &&
        get(currentAddress) === snap.address &&
        vnModeFromParsed(get(parsedHash), get(currentProject), snap.address)
      ) {
        try {
          const data = await getPlayback(snap.address)
          vnPlayback.set(data)
          const slug = get(currentProject)!
          const tts = resolveVisualNovelTtsSettings(get(parsedHash))
          const eligible = vnCursorCliSlotEligible(get(stats), snap.address, data.items)
          vnPlaybackItemCount.set(vnLogicalStepCount(data.items, eligible))
          const maxIx = data.items.length - 1 + (eligible ? 1 : 0)
          const appended = data.items.length > snap.itemCount
          const newTailId = playbackTailTextId(data.items)
          const tailReplaced = !appended && newTailId !== snap.lastTextId

          let nextIx: number
          if (appended) {
            nextIx = snap.itemCount
          } else if (tailReplaced) {
            nextIx = Math.max(0, data.items.length - 1)
          } else {
            nextIx = eligible ? data.items.length : Math.max(0, data.items.length - 1)
          }
          nextIx = Math.min(Math.max(nextIx, 0), maxIx)
          const nextLogical = playbackIndexToLogicalStep(data.items, nextIx)
          setVisualNovelHash(slug, snap.address, nextLogical, tts)
        } catch (err) {
          vnError.set(err instanceof Error ? err.message : String(err))
        }
      }
    } catch (e) {
      console.error('CLI done refresh failed:', e)
    }
  }

  function applyKbFromUrl(kb: string | null) {
    const currentKb = get(selectedKbId)
    const currentOpen = get(kbPanelOpen)

    if (kb) {
      if (kb === currentKb && currentOpen) return
      const dotIndex = kb.indexOf('.')
      const type = dotIndex > 0 ? kb.slice(0, dotIndex) : ''
      kbFilters.set({ type, tags: [] })
      selectedKbId.set(kb)
      kbPanelOpen.set(true)
    } else {
      if (!currentOpen) return
      kbPanelOpen.set(false)
    }
  }

  async function handleHashChange() {
    syncUrlHashFromWindow()
    const { project, path, kb } = parseHash(window.location.hash)
    const currentSlug = get(currentProject)
    if (project && project !== currentSlug) {
      await switchProject(project)
      applyKbFromUrl(kb)
      return
    }
    const addr = get(currentAddress)
    if (path && path !== addr) navigate(path)
    applyKbFromUrl(kb)
  }

  onMount(async () => {
    syncUrlHashFromWindow()
    onAfterMutation(() => { void getStats().then(applyStats) })

    try {
      // 1. Load project list
      const projectList = await getProjects()
      const slugs = projectList.map(p => p.slug)
      availableProjects.set(slugs)

      // 2. Pick project from hash or default to first
      const { project: hashProject, path, kb } = parseHash(window.location.hash)
      const selectedSlug = (hashProject && slugs.includes(hashProject))
        ? hashProject : (slugs[0] ?? null)
      if (!selectedSlug) { console.error('No projects available'); return }
      currentProject.set(selectedSlug)

      // 3. Fetch stats (now uses projectPath() via currentProject store)
      const initialStats = await getStats()
      applyStats(initialStats)

      // 4. Navigate
      if (path) {
        try {
          inlineEditMode.set(null)
          const data = await getNode(path)
          currentAddress.set(data.address)
          nodeContent.set(data.content)
          const priorHash = window.location.hash
          window.location.hash =
            '#' + hashAfterNodeResolved(selectedSlug, data.address, hashKbParam(), priorHash)
        } catch {
          window.location.hash = buildHash('', kb)
          await navigate(initialStats.cursor || '')
        }
      } else {
        await navigate(initialStats.cursor || '')
      }
      applyKbFromUrl(kb)
    } catch (e) { console.error('Init failed:', e) }
  })
</script>

<svelte:window onhashchange={handleHashChange} />

<MainLayout>
  {#snippet topbar()}
    {#if !(vnActive && $vnImageExplore)}
      <TopBar />
    {/if}
  {/snippet}

  {#if $currentProject}
    {#if $inlineEditMode !== null}
      <InlineEditView />
    {:else if vnActive}
      <VisualNovelView onCliDone={handleCliDone} {navigate} />
    {:else}
      <div
        class={['narrative-content', { 'kb-open': $kbPanelOpen }]}
      >
        <TreeBrowser {navigate} onProjectSwitch={switchProject} />
        <MarkdownView />
      </div>
      {#if $kbPanelOpen}
        <KbPanel />
      {/if}
    {/if}
  {/if}
  <CliOutputPanel />
  <TransactionResultPanel />
  <StreamingPreviewPanel />
  <MediaPreviewCarousel />
  <MediaCarousel onDone={handleCarouselDone} />
  <KbDiffModal />

  {#snippet bottombar()}
    {#if !vnActive}
      <Cli onCliDone={handleCliDone} navigate={navigate} syncLocation={syncLocation} />
    {/if}
  {/snippet}
</MainLayout>
