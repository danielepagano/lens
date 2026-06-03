<script lang="ts">
  import { onMount } from 'svelte'
  import { get } from 'svelte/store'
  import {
    cliInputRequest,
    mediaCarouselRequest,
    mediaPreviewSession,
    mountCacheRefreshTrigger,
    cliOutput,
  } from '../../stores/ui'
  import { saveGeneratedItem, type MountEntry } from '../../services/api'
  import type { MediaStartEvent } from '../../services/api'
  import MediaStrip from './MediaStrip.svelte'
  import MediaSpotlight from './MediaSpotlight.svelte'

  const previewTitle = 'Generate preview'
  let closeConfirm = $state(false)
  /** When set, confirming discard also pre-fills the CLI (New batch flow). */
  let pendingNewBatchCli = $state<string | null>(null)
  let nowMs = $state(Date.now())

  function hasUnsavedPreviewItems(): boolean {
    const s = get(mediaPreviewSession)
    return (s?.items ?? []).some((i) => i.saved !== true)
  }

  onMount(() => {
    const id = window.setInterval(() => {
      nowMs = Date.now()
    }, 400)
    return () => window.clearInterval(id)
  })

  let previewState = $derived($mediaPreviewSession)
  let hasStart = $derived(previewState?.start != null)
  let elapsedSec = $derived(
    previewState && previewState.generationStartedAt != null
      ? Math.max(0, Math.floor((nowMs - previewState.generationStartedAt) / 1000))
      : 0
  )

  let batchTotal = $derived(previewState?.start?.batch_size)
  let startForUi = $derived(previewState?.start ?? null)
  let items = $derived(previewState?.items ?? [])
  let entries = $derived.by((): MountEntry[] => {
    if (!previewState) return []
    const byIdx = new Map(items.map((it) => [it.index, it]))
    const maxIdxFromItems = items.length ? Math.max(...items.map((it) => it.index)) : -1
    const floor = batchTotal != null ? batchTotal : 0
    const n = Math.max(floor, maxIdxFromItems + 1)
    if (n <= 0) return []
    const out: MountEntry[] = []
    for (let idx = 0; idx < n; idx++) {
      const it = byIdx.get(idx)
      if (it) {
        out.push({ name: `r_${it.index}.${it.ext}`, is_dir: false })
      } else {
        out.push({ name: `_pending_${idx}`, is_dir: false, placeholder: true })
      }
    }
    return out
  })

  let savedNames = $derived(
    new Set(items.filter((it) => it.saved).map((it) => `r_${it.index}.${it.ext}`))
  )

  let selectedEntry = $derived(
    previewState && previewState.selectedIndex >= 0 && previewState.selectedIndex < entries.length
      ? entries[previewState.selectedIndex] ?? null
      : null
  )
  let selectedItem = $derived(
    selectedEntry && !selectedEntry.placeholder
      ? items.find((it) => `r_${it.index}.${it.ext}` === selectedEntry.name) ?? null
      : null
  )
  let selectedPath = $derived(selectedItem ? `r_${selectedItem.index}.${selectedItem.ext}` : null)

  const PREVIEW_IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif'])
  let selectedIsImage = $derived(
    !!(selectedItem && PREVIEW_IMAGE_EXT.has(selectedItem.ext.toLowerCase()))
  )

  let imageChromeless = $state(false)
  let prevPreviewSpotlightPath: string | null = null

  $effect(() => {
    if (selectedPath !== prevPreviewSpotlightPath) {
      prevPreviewSpotlightPath = selectedPath
      imageChromeless = false
    }
  })

  function handleToggleImageChromeless() {
    if (!selectedIsImage) return
    imageChromeless = !imageChromeless
  }

  function getDataUrl(name: string): string | undefined {
    if (!previewState) return undefined
    const m = /^r_(\d+)\.([^.]+)$/.exec(name)
    if (!m) return undefined
    const idx = parseInt(m[1] ?? '0', 10)
    const it = previewState.items.find((i) => i.index === idx)
    return it?.src
  }

  function newBatchRepopulate() {
    if (!previewState?.start) return
    const st = previewState.start
    const rp = previewState.rawParams
    const sp = (s: string) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    const pathTok = (p: string) => (/^[\w./-]+$/.test(p) ? p : `"${sp(p)}"`)
    const parts: string[] = ['/media-generate']
    const ptext = (rp.prompt ?? '').trim()
    if (ptext) parts.push(`"${sp(ptext)}"`)
    const fromPath = (rp.from ?? '').trim()
    if (fromPath) parts.push(`--from ${pathTok(fromPath)}`)
    if (st.model_id) parts.push(`--model ${st.model_id}`)
    if (st.batch_size) parts.push(`--batch ${st.batch_size}`)
    if (st.aspect) parts.push(`--aspect ${st.aspect}`)
    if (st.size) parts.push(`--size ${st.size}`)
    if (st.slug) parts.push(`--slug ${st.slug}`)
    if (st.negative) parts.push(`--negative "${sp(String(st.negative))}"`)
    for (const r of rp.refs ?? []) {
      const t = String(r).trim()
      if (t) parts.push(`--ref ${pathTok(t)}`)
    }
    const line = parts.join(' ')
    if (hasUnsavedPreviewItems()) {
      pendingNewBatchCli = line
      closeConfirm = true
      return
    }
    pendingNewBatchCli = null
    closeConfirm = false
    mediaPreviewSession.set(null)
    cliInputRequest.set(line)
  }

  function close(skipConfirm: boolean) {
    if (skipConfirm) {
      const line = pendingNewBatchCli
      pendingNewBatchCli = null
      closeConfirm = false
      mediaPreviewSession.set(null)
      if (line !== null) {
        cliInputRequest.set(line)
      }
      return
    }
    if (closeConfirm) {
      closeConfirm = false
      pendingNewBatchCli = null
      return
    }
    if (hasUnsavedPreviewItems()) {
      closeConfirm = true
      return
    }
    pendingNewBatchCli = null
    closeConfirm = false
    mediaPreviewSession.set(null)
  }

  function openBrowse() {
    if (previewState === null || previewState.start === null || previewState.batchSeq === null) return
    const sub = `generated/${previewState.start.slug}`
    close(true)
    mediaCarouselRequest.set({ mode: 'manage', dir: sub })
  }

  function handleSelect(index: number) {
    mediaPreviewSession.update((p) => (p ? { ...p, selectedIndex: index } : p))
  }

  function handlePreview(index: number) {
    mediaPreviewSession.update((p) => (p ? { ...p, selectedIndex: index } : p))
  }

  function handleDeselect() {
    mediaPreviewSession.update((p) => (p ? { ...p, selectedIndex: -1 } : p))
  }

  function batchParamsForSave(start: MediaStartEvent) {
    return {
      prompt_raw: start.prompt_raw,
      prompt_resolved: start.prompt_resolved,
      model_id: start.model_id,
      aspect_ratio: start.aspect,
      size: start.size,
      batch_size: start.batch_size,
      negative: start.negative ?? null,
      ...(start.refs?.length ? { refs: start.refs } : {}),
    }
  }

  async function handleSave() {
    if (!previewState?.start || !selectedItem) return
    if (selectedItem.saved) return
    const start = previewState.start
    const slug = start.slug
    const itemIndex = selectedItem.index
    mediaPreviewSession.update((p) => {
      if (!p) return p
      return {
        ...p,
        items: p.items.map((it) =>
          it.index === itemIndex ? { ...it, saving: true } : it
        ),
      }
    })
    try {
      const out = await saveGeneratedItem({
        slug,
        batch_seq: previewState.batchSeq,
        batch_params: batchParamsForSave(start),
        item: { index: itemIndex, ext: selectedItem.ext, b64: selectedItem.b64 },
      })
      mediaPreviewSession.update((p) => {
        if (!p) return p
        return {
          ...p,
          batchSeq: out.batch_seq,
          items: p.items.map((it) =>
            it.index === itemIndex
              ? { ...it, saved: true, saving: false, resultSeq: out.result_seq, savedPath: out.path }
              : it
          ),
        }
      })
      mountCacheRefreshTrigger.update((n) => n + 1)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      mediaPreviewSession.update((p) => {
        if (!p) return p
        return {
          ...p,
          items: p.items.map((it) =>
            it.index === itemIndex ? { ...it, saving: false } : it
          ),
        }
      })
      cliOutput.set({ output: msg, exitCode: 1, streaming: false })
    }
  }
</script>

{#if previewState}
  <div
    class={['carousel-overlay media-preview-overlay', imageChromeless && 'carousel-image-only']}
    role="dialog"
    aria-modal="true"
    aria-label={previewTitle}
  >
    <div class="carousel-header">
      <div class="carousel-header-top media-preview-header-row">
        <span class="carousel-title">{previewTitle}</span>
        <div class="preview-header-actions">
          <button
            type="button"
            class="carousel-ghost-btn preview-tight-btn"
            title="Re-fill CLI to run a new batch"
            onclick={newBatchRepopulate}
            disabled={!hasStart}
          >New batch</button>
          <button
            type="button"
            class="carousel-ghost-btn preview-tight-btn"
            onclick={openBrowse}
            disabled={!hasStart || previewState.batchSeq === null}
          >Browse results</button>
        </div>
        {#if closeConfirm}
          <div class="preview-confirm" role="alert">
            <span class="preview-confirm-text">Discard {previewState.items.filter((i) => i.saved !== true).length} unsaved?</span>
            <button type="button" class="preview-tight-btn" onclick={() => close(true)}>Discard</button>
            <button
              type="button"
              class="preview-tight-btn"
              onclick={() => {
                closeConfirm = false
                pendingNewBatchCli = null
              }}
            >Back</button>
          </div>
        {:else}
          <button type="button" class="carousel-close preview-close-x" aria-label="Close" onclick={() => close(false)}>✕</button>
        {/if}
      </div>
      <div class="preview-status-line" aria-live="polite">
        {#if !hasStart && previewState.status === 'streaming'}
          Preparing… {elapsedSec}s
        {:else if hasStart && previewState.status === 'streaming' && startForUi}
          Generating {previewState.items.length}/{startForUi.batch_size} · {elapsedSec}s
        {:else if previewState.status === 'done' && hasStart && startForUi}
          Done — {previewState.items.length} image{previewState.items.length === 1 ? '' : 's'} · {elapsedSec}s
        {:else if previewState.status === 'error' && hasStart}
          Stopped · {elapsedSec}s
        {:else if previewState.status === 'error' && !hasStart}
          Failed · {elapsedSec}s
        {/if}
      </div>
    </div>

    <div class="carousel-body">
      {#if previewState.error && !previewState.items.length}
        <div class="carousel-error" role="alert">{previewState.error}</div>
      {:else}
        <MediaStrip
          {entries}
          selectedIndex={previewState.selectedIndex}
          currentDir=""
          compact={true}
          {getDataUrl}
          {savedNames}
          onSelect={handleSelect}
          onPreview={handlePreview}
        />
      {/if}

      {#if selectedItem && hasStart}
        <MediaSpotlight
          path={selectedPath}
          refCopyPath={selectedItem.saved && selectedItem.savedPath ? selectedItem.savedPath : null}
          mode="preview"
          previewSrc={selectedItem.src}
          saved={selectedItem.saved}
          saving={selectedItem.saving}
          chromeless={imageChromeless}
          onClose={handleDeselect}
          onSave={handleSave}
          onToggleChromeless={handleToggleImageChromeless}
        />
      {/if}

      {#if previewState.error && previewState.items.length}
        <div class="carousel-error" role="alert">{previewState.error}</div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .media-preview-header-row {
    gap: 0.35rem;
    flex-wrap: wrap;
  }
  .preview-header-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    align-items: center;
    margin: 0;
  }
  .carousel-ghost-btn.preview-tight-btn {
    padding: 0.12rem 0.4rem;
    margin: 0;
    font-size: 0.72rem;
  }
  .preview-close-x {
    padding: 0.08rem 0.28rem !important;
    min-height: unset !important;
    margin: 0 !important;
    line-height: 1.1;
  }
  .preview-confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    margin: 0;
    font-size: 0.78rem;
    color: var(--pico-color, inherit);
  }
  .preview-confirm-text {
    margin-right: 0.15rem;
  }
  .preview-tight-btn {
    padding: 0.1rem 0.35rem;
    margin: 0;
    font-size: 0.72rem;
    line-height: 1.2;
  }
  .preview-status-line {
    font-size: 0.78rem;
    opacity: 0.75;
    padding: 0.1rem 0 0;
    min-height: 1.15rem;
  }
  .carousel-ghost-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .carousel-error {
    padding: 0.75rem 1rem;
    color: var(--pico-del-color, #e05c5c);
    font-size: 0.85rem;
  }
</style>
