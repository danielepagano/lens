<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import MainLayout from './layout/MainLayout.svelte'
  import TopBar from './layout/TopBar.svelte'
  import BottomBar from './layout/BottomBar.svelte'
  import TreeBrowser from './features/tree/TreeBrowser.svelte'
  import MarkdownView from './features/viewer/MarkdownView.svelte'
  import { getStats, getNode, getTransaction } from './services/api'
  import { currentAddress, nodeContent, transactionState } from './stores/document'
  import { activeNarrative, availableNarratives, cursor } from './stores/session'

  async function navigate(addr: string): Promise<void> {
    if (!addr) return
    try {
      const [data, tx] = await Promise.all([
        getNode(addr),
        getTransaction().catch((e) => {
          console.error('Transaction fetch failed:', e)
          return null
        }),
      ])
      currentAddress.set(data.address)
      nodeContent.set(data.content)
      transactionState.set(tx?.has_pending ? tx : null)
      window.location.hash = data.address
    } catch (e) {
      console.error('Navigation failed:', e)
      transactionState.set(null)
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

  <TreeBrowser {navigate} />
  <MarkdownView />

  <svelte:fragment slot="bottombar">
    <BottomBar />
  </svelte:fragment>
</MainLayout>
