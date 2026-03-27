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
  import KbSidebar from './features/kb/KbSidebar.svelte'
  import KbViewer from './features/kb/KbViewer.svelte'
  import InlineEditView from './features/editor/InlineEditView.svelte'
  import { getStats, getNode, onAfterMutation } from './services/api'
  import { currentAddress, nodeContent } from './stores/document'
  import { applyStats, stats } from './stores/stats'
  import { appMode, selectedKbId, kbFilters, inlineEditMode } from './stores/ui'

  function hashKbParam(): string | null {
    return get(appMode) === 'kb' ? get(selectedKbId) : null
  }

  interface ParsedHash {
    path: string
    kb: string | null
  }

  function parseHash(hash: string): ParsedHash {
    const raw = decodeURIComponent(hash.slice(1))
    const qIndex = raw.indexOf('?')
    if (qIndex === -1) {
      return { path: raw, kb: null }
    }
    const path = raw.slice(0, qIndex)
    const query = raw.slice(qIndex + 1)
    const params = new URLSearchParams(query)
    return { path, kb: params.get('kb') }
  }

  function buildHash(path: string, kb: string | null): string {
    if (!kb) return path
    return `${path}?kb=${encodeURIComponent(kb)}`
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
    const currentMode = get(appMode)

    if (kb) {
      if (kb === currentKb && currentMode === 'kb') return
      const dotIndex = kb.indexOf('.')
      const type = dotIndex > 0 ? kb.slice(0, dotIndex) : ''
      kbFilters.set({ type, tags: [] })
      selectedKbId.set(kb)
      appMode.set('kb')
    } else {
      if (currentKb === null && currentMode === 'narrative') return
      selectedKbId.set(null)
      appMode.set('narrative')
    }
  }

  function handleHashChange() {
    const { path, kb } = parseHash(window.location.hash)
    const addr = get(currentAddress)
    if (path && path !== addr) {
      navigate(path)
    }
    applyKbFromUrl(kb)
  }

  onMount(async () => {
    window.addEventListener('hashchange', handleHashChange)
    onAfterMutation(() => { void getStats().then(applyStats) })

    try {
      const stats = await getStats()
      applyStats(stats)

      const { path, kb } = parseHash(window.location.hash)
      await navigate(path || stats.cursor || '')
      applyKbFromUrl(kb)
    } catch (e) {
      console.error('Init failed:', e)
    }
  })

  onDestroy(() => {
    window.removeEventListener('hashchange', handleHashChange)
  })
</script>

<MainLayout>
  <svelte:fragment slot="topbar">
    <TopBar />
  </svelte:fragment>

  {#if $inlineEditMode !== null}
    <InlineEditView />
  {:else if $appMode === 'narrative'}
    <TreeBrowser {navigate} />
    <MarkdownView />
  {:else}
    <KbSidebar />
    <KbViewer />
  {/if}
  <CliOutputPanel />
  <TransactionResultPanel />
  <StreamingPreviewPanel />
  <MediaUploadPanel />
  <MediaRemovePanel />
  <MediaPreviewPanel />

  <svelte:fragment slot="bottombar">
    <Cli onCliDone={handleCliDone} navigate={navigate} />
  </svelte:fragment>
</MainLayout>
