<script lang="ts">
  import { onMount } from 'svelte'
  import MainLayout from './layout/MainLayout.svelte'
  import TopBar from './layout/TopBar.svelte'
  import BottomBar from './layout/BottomBar.svelte'
  import TreeBrowser from './features/tree/TreeBrowser.svelte'
  import MarkdownView from './features/viewer/MarkdownView.svelte'
  import { getStats, getNode } from './services/api'
  import { currentAddress, nodeContent } from './stores/document'

  onMount(async () => {
    try {
      const stats = await getStats()
      if (stats.cursor) {
        const data = await getNode(stats.cursor)
        currentAddress.set(data.address)
        nodeContent.set(data.content)
      }
    } catch (e) {
      console.error('Init failed:', e)
    }
  })
</script>

<MainLayout>
  <svelte:fragment slot="topbar">
    <TopBar />
  </svelte:fragment>

  <TreeBrowser />
  <MarkdownView />

  <svelte:fragment slot="bottombar">
    <BottomBar />
  </svelte:fragment>
</MainLayout>
