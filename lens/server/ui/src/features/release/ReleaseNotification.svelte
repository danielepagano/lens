<script lang="ts">
  import { stats } from '../../stores/stats'
  import { releaseModalOpen } from '../../stores/ui'

  const rls = $derived($stats?.release)
  const pending = $derived(rls?.gated_update_pending ?? false)
  const approved = $derived(rls?.gated_update_approved ?? false)

  function open() {
    releaseModalOpen.set(true)
  }
</script>

{#if pending}
  <button
    class="release-indicator"
    class:approved
    onclick={open}
    aria-label={approved ? 'Update approved, awaiting deployment' : 'New release pending'}
    title={approved ? 'Approved — awaiting deployment' : 'Update available'}
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

  .release-indicator.approved {
    background: var(--pico-ins-color, #2ea043);
  }
</style>
