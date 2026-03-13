<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import MainLayout from './layout/MainLayout.svelte'
  import TopBar from './layout/TopBar.svelte'
  import BottomBar from './layout/BottomBar.svelte'
  import TreeBrowser from './features/tree/TreeBrowser.svelte'
  import MarkdownView from './features/viewer/MarkdownView.svelte'
  import CliOutputPanel from './features/cli/CliOutputPanel.svelte'
  import TransactionResultPanel from './features/transaction/TransactionResultPanel.svelte'
  import KbSidebar from './features/kb/KbSidebar.svelte'
  import KbViewer from './features/kb/KbViewer.svelte'
  import { getStats, getNode } from './services/api'
  import { currentAddress, nodeContent, transactionState } from './stores/document'
  import {
    activeNarrative,
    availableNarratives,
    cursor,
    effectivePinsAtCursor,
  } from './stores/session'
  import { appMode, kbTypes } from './stores/ui'
  import { currentDatasets } from './stores/session'
  import { updateDatasetCommands } from './commands/handlers'

  async function navigate(addr: string): Promise<void> {
    if (!addr) return
    try {
      const data = await getNode(addr)
      currentAddress.set(data.address)
      nodeContent.set(data.content)
      window.location.hash = data.address
    } catch (e) {
      console.error('Navigation failed:', e)
    }
  }

  async function handleCliDone(): Promise<void> {
    const prevCursor = get(cursor)
    const addr = get(currentAddress)
    try {
      const stats = await getStats()
      availableNarratives.set(stats.narratives ?? [])
      activeNarrative.set(stats.active_narrative)
      cursor.set(stats.cursor ?? null)
      effectivePinsAtCursor.set(stats.effective_pins_at_cursor ?? [])
      transactionState.set(stats.transaction ?? null)
      kbTypes.set(stats.kb_types ?? [])
      currentDatasets.set(stats.current_datasets ?? [])
      updateDatasetCommands(stats.current_datasets ?? [])
      if (addr) {
        const data = await getNode(addr)
        nodeContent.set(data.content)
      }
      const newCursor = get(cursor)
      if (prevCursor === addr && newCursor !== prevCursor && newCursor) {
        navigate(newCursor)
      }
    } catch (e) {
      console.error('CLI done refresh failed:', e)
    }
  }

  function handleHashChange() {
    const addr = decodeURIComponent(window.location.hash.slice(1))
    if (addr && addr !== get(currentAddress)) {
      navigate(addr)
    }
  }

  onMount(async () => {
    window.addEventListener('hashchange', handleHashChange)

    try {
      const stats = await getStats()
      availableNarratives.set(stats.narratives ?? [])
      activeNarrative.set(stats.active_narrative)
      cursor.set(stats.cursor ?? null)
      effectivePinsAtCursor.set(stats.effective_pins_at_cursor ?? [])
      transactionState.set(stats.transaction ?? null)
      kbTypes.set(stats.kb_types ?? [])
      currentDatasets.set(stats.current_datasets ?? [])
      updateDatasetCommands(stats.current_datasets ?? [])

      const initial = decodeURIComponent(window.location.hash.slice(1))
      await navigate(initial || stats.cursor || '')
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

  {#if $appMode === 'narrative'}
    <TreeBrowser {navigate} />
    <MarkdownView />
  {:else}
    <KbSidebar />
    <KbViewer />
  {/if}
  <CliOutputPanel />
  <TransactionResultPanel />

  <svelte:fragment slot="bottombar">
    <BottomBar onCliDone={handleCliDone} />
  </svelte:fragment>
</MainLayout>
