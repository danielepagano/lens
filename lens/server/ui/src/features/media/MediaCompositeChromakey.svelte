<script lang="ts">
  import { mediaCompositeSession } from '../../stores/ui'
  import {
    buildChromakeyParams,
    runChromakeyPreview,
    runChromakeySave,
    type ChromakeyOverrideInputs,
  } from './mediaCompositeHandlers'

  let session = $derived($mediaCompositeSession)
  let busy = $derived(session?.status === 'previewing' || session?.status === 'saving')

  let keyInput = $state('')
  let coreTolInput = $state('')
  let residualThreshInput = $state('')
  let dilatePxInput = $state('')

  let seededForPath: string | null = null
  $effect(() => {
    if (session && session.path !== seededForPath) {
      seededForPath = session.path
      keyInput = ''
      coreTolInput = ''
      residualThreshInput = ''
      dilatePxInput = ''
    } else if (!session) {
      seededForPath = null
    }
  })

  function close() {
    mediaCompositeSession.set(null)
  }

  function currentInputs(): ChromakeyOverrideInputs {
    return {
      key: keyInput,
      coreTol: coreTolInput,
      residualThresh: residualThreshInput,
      dilatePx: dilatePxInput,
    }
  }

  function handlePreview() {
    if (!session || busy) return
    void runChromakeyPreview(buildChromakeyParams(session.path, currentInputs()))
  }

  function handleSave() {
    if (!session || busy || session.status !== 'ready') return
    void runChromakeySave()
  }
</script>

{#if session}
  <div class="carousel-overlay" role="dialog" aria-modal="true" aria-label="Chromakey preview">
    <div class="carousel-header">
      <div class="carousel-header-top">
        <span class="carousel-title">Chromakey — {session.path}</span>
        <button type="button" class="carousel-close" aria-label="Close" onclick={close}>✕</button>
      </div>
    </div>

    <div class="carousel-body">
      <div class="composite-controls">
        <label>
          Key
          <input type="text" placeholder="auto" bind:value={keyInput} disabled={busy} />
        </label>
        <label>
          Core tol
          <input type="text" inputmode="decimal" placeholder="auto" bind:value={coreTolInput} disabled={busy} />
        </label>
        <label>
          Residual thresh
          <input
            type="text"
            inputmode="decimal"
            placeholder="10.0"
            bind:value={residualThreshInput}
            disabled={busy}
          />
        </label>
        <label>
          Dilate px
          <input type="text" inputmode="numeric" placeholder="auto" bind:value={dilatePxInput} disabled={busy} />
        </label>
        <button type="button" onclick={handlePreview} disabled={busy}>
          {session.status === 'previewing' ? 'Previewing…' : 'Preview'}
        </button>
      </div>

      {#if session.status === 'ready' || session.status === 'saving' || session.status === 'saved'}
        <div class="composite-resolved" aria-live="polite">
          resolved: key {session.keyHex} · core_tol {session.coreTol?.toFixed(1)} · residual_thresh {session.residualThresh}
          · dilate_px {session.dilatePx} · {session.nCornersUsed}/4 corners
        </div>
      {/if}

      {#if session.error}
        <div class="carousel-error" role="alert">{session.error}</div>
      {/if}

      <div class="carousel-spotlight">
        {#if session.previewSrc}
          <img src={session.previewSrc} alt="Chromakey preview" />
        {:else}
          <span class="carousel-spotlight-placeholder">Previewing…</span>
        {/if}
      </div>

      <div class="carousel-actions">
        {#if session.savedPath}
          <span class="composite-saved-path">Saved: {session.savedPath}</span>
        {/if}
        <button
          type="button"
          class="action-primary"
          disabled={session.status !== 'ready' && session.status !== 'saved'}
          onclick={handleSave}
        >
          {session.status === 'saved' ? 'Saved' : session.status === 'saving' ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .composite-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: flex-end;
    padding: 0.6rem 0.9rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
  }
  .composite-controls label {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: 0.72rem;
    opacity: 0.85;
    margin: 0;
  }
  .composite-controls input {
    width: 8rem;
    font-size: 0.85rem;
    padding: 0.2rem 0.4rem;
    margin: 0;
  }
  .composite-resolved {
    padding: 0.35rem 0.9rem 0;
    font-size: 0.75rem;
    opacity: 0.7;
  }
  .composite-saved-path {
    font-size: 0.78rem;
    opacity: 0.75;
    margin-right: auto;
  }
  .carousel-error {
    padding: 0.75rem 1rem;
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.85rem;
  }
</style>
