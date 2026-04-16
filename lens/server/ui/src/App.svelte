<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import MainLayout from './layout/MainLayout.svelte'
  import TopBar from './layout/TopBar.svelte'
  import Cli from './layout/Cli.svelte'
  import TreeBrowser from './features/tree/TreeBrowser.svelte'
  import MarkdownView from './features/viewer/MarkdownView.svelte'
  import CliOutputPanel from './features/cli/CliOutputPanel.svelte'
  import TransactionResultPanel from './features/transaction/TransactionResultPanel.svelte'
  import StreamingPreviewPanel from './features/streaming/StreamingPreviewPanel.svelte'
  import MediaUploadPanel from './features/cli/MediaUploadPanel.svelte'
  import MediaRemovePanel from './features/cli/MediaRemovePanel.svelte'
  import MediaPreviewPanel from './features/cli/MediaPreviewPanel.svelte'
  import KbDiffModal from './features/kb/KbDiffModal.svelte'
  import KbPanel from './features/kb/KbPanel.svelte'
  import InlineEditView from './features/editor/InlineEditView.svelte'
  import { getStats, getNode, getProjects, onAfterMutation } from './services/api'
  import { currentAddress, nodeContent } from './stores/document'
  import { applyStats, stats } from './stores/stats'
  import { kbPanelOpen, selectedKbId, kbFilters, inlineEditMode, editorFocused, treeRefreshTrigger } from './stores/ui'
  import { currentProject, availableProjects } from './stores/project'

  $: document.body.classList.toggle('editor-focused', $editorFocused)

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

  async function handleCliDone(): Promise<void> {
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
    window.addEventListener('hashchange', handleHashChange)
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
          window.location.hash = buildHash(data.address, hashKbParam())
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

  onDestroy(() => {
    window.removeEventListener('hashchange', handleHashChange)
  })
</script>

<MainLayout>
  <svelte:fragment slot="topbar">
    <TopBar />
  </svelte:fragment>

  {#if $currentProject}
    {#if $inlineEditMode !== null}
      <InlineEditView />
    {:else}
      <div class="narrative-content" class:kb-open={$kbPanelOpen}>
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
  <MediaUploadPanel />
  <MediaRemovePanel />
  <MediaPreviewPanel />
  <KbDiffModal />

  <svelte:fragment slot="bottombar">
    <Cli onCliDone={handleCliDone} navigate={navigate} />
  </svelte:fragment>
</MainLayout>
