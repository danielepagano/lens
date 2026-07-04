<script lang="ts">
  import { stats } from '../../stores/stats'
  import { releaseModalOpen } from '../../stores/ui'

  const rls = $derived($stats?.release)
  const latestAvailable = $derived(rls?.latest_available ?? '')
  const installedVersion = $derived(rls?.installed_version ?? '')
  const hasNewer = $derived(
    !!latestAvailable && !!installedVersion && latestAvailable !== installedVersion
  )

  function open() {
    releaseModalOpen.set(true)
  }
</script>

{#if hasNewer}
  <button
    class="release-indicator"
    onclick={open}
    aria-label="New release available"
    title="{latestAvailable} available"
  ></button>
{/if}

<style>
  .release-indicator {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 50%;
    border: none;
    background: var(--pico-del-color, #da3633);
    cursor: pointer;
    flex-shrink: 0;
    margin-left: 0.35rem;
    padding: 0;
  }
</style>
