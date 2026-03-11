<script lang="ts">
  import KbBrowser from './KbBrowser.svelte'
  import { treeOpen } from '../../stores/ui'

  function close() {
    treeOpen.set(false)
  }
</script>

<div class="sidebar" class:open={$treeOpen} data-testid="kb-browser">
  <div class="sidebar-header">
    <strong>Knowledge Base</strong>
    <button class="sidebar-close" on:click={close} aria-label="Close">✕</button>
  </div>
  <div class="sidebar-body kb-sidebar-body">
    <KbBrowser onSelect={close} />
  </div>
</div>

