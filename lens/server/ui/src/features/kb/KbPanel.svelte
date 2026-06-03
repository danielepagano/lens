<script lang="ts">
  import KbBrowser from './KbBrowser.svelte'
  import KbViewer from './KbViewer.svelte'
  import HamburgerIcon from '../../components/icons/HamburgerIcon.svelte'
  import CloseIcon from '../../components/icons/CloseIcon.svelte'
  import { treeOpen } from '../../stores/ui'

  const isTreeOpen = $derived($treeOpen)

  function openBrowser() {
    treeOpen.set(true)
  }

  function closeBrowser() {
    treeOpen.set(false)
  }
</script>

<div class="kb-panel" data-testid="kb-panel">
  {#if isTreeOpen}
    <div class="kb-browser-overlay" data-testid="kb-browser">
      <div class="sidebar-header">
        <strong>Knowledge Base</strong>
        <button class="sidebar-close" onclick={closeBrowser} aria-label="Close browser">
          <CloseIcon size={18} />
        </button>
      </div>
      <div class="sidebar-body kb-sidebar-body">
        <KbBrowser onSelect={closeBrowser} />
      </div>
    </div>
  {/if}
  <div class="kb-panel-main">
    <div class="kb-panel-toolbar">
      <button class="kb-browse-btn" onclick={openBrowser} aria-label="Browse knowledge base">
        <HamburgerIcon size={20} />
      </button>
      <span class="kb-panel-title">Knowledge Base</span>
    </div>
    <KbViewer />
  </div>
</div>
