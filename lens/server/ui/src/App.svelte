<script lang="ts">
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import MainLayout from './layout/MainLayout.svelte'
  import TopBar from './layout/TopBar.svelte'
  import BottomBar from './layout/BottomBar.svelte'
  import TreeBrowser from './features/tree/TreeBrowser.svelte'
  import MarkdownView from './features/viewer/MarkdownView.svelte'
  import { getStats, getNode } from './services/api'
  import { currentAddress, nodeContent } from './stores/document'

  async function navigate(addr: string): Promise<void> {
    try {
      const data = await getNode(addr)
      currentAddress.set(data.address)
      nodeContent.set(data.content)
      window.location.hash = data.address
    } catch (e) {
      console.error('Navigation failed:', e)
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

    const initial = decodeURIComponent(window.location.hash.slice(1))
    if (initial) {
      await navigate(initial)
    } else {
      try {
        const stats = await getStats()
        if (stats.cursor) {
          await navigate(stats.cursor)
        }
      } catch (e) {
        console.error('Init failed:', e)
      }
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
