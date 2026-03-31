<script lang="ts">
  import KbBrowser from './KbBrowser.svelte'
  import KbViewer from './KbViewer.svelte'
  import HamburgerIcon from '../../components/icons/HamburgerIcon.svelte'
  import CloseIcon from '../../components/icons/CloseIcon.svelte'
  import { treeOpen, kbPanelOpen } from '../../stores/ui'
  import { currentAddress } from '../../stores/document'
  import { get } from 'svelte/store'

  function closeBrowser() {
    treeOpen.set(false)
  }

  function closePanel() {
    kbPanelOpen.set(false)
    const addr = get(currentAddress) || ''
    window.location.hash = addr
  }
</script>

<div class="kb-panel" data-testid="kb-panel">
  {#if $treeOpen}
    <div class="kb-browser-overlay">
      <div class="sidebar-header">
        <strong>Knowledge Base</strong>
        <button class="sidebar-close" on:click={closeBrowser} aria-label="Close browser">
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
      <button class="kb-browse-btn" on:click={() => treeOpen.set(true)} aria-label="Browse knowledge base">
        <HamburgerIcon size={20} />
      </button>
      <span class="kb-panel-title">Knowledge Base</span>
      <button class="kb-panel-close" on:click={closePanel} aria-label="Close knowledge base panel">
        <CloseIcon size={18} />
      </button>
    </div>
    <KbViewer />
  </div>
</div>
