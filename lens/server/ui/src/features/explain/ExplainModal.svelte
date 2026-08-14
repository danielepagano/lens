<script lang="ts">
  import { getExplain, type ExplainReport } from '../../services/api'
  import { explainRequest } from '../../stores/ui'
  import { stats } from '../../stores/stats'
  import { currentProject } from '../../stores/project'
  import { currentAddress } from '../../stores/document'
  import { availableOperatorSlugs } from '../../commands/common'
  import ExplainBar from './ExplainBar.svelte'
  import ExplainBlockSection from './ExplainBlockSection.svelte'
  import SelectMenu from '../../components/SelectMenu.svelte'
  import {
    blockSegments,
    formatShare,
    formatSize,
    prefixShare,
    reportHeadline,
    sizeOf,
    type ExplainUnit,
  } from './explainModel'

  let dialog: HTMLDialogElement | undefined

  const request = $derived($explainRequest)

  let unit = $state<ExplainUnit>('tokens')
  let operatorOverride = $state('')
  let reloadSeq = $state(0)
  let report = $state<ExplainReport | null>(null)
  let loading = $state(false)
  let error = $state<string | null>(null)
  let selectedBlock = $state<string | null>(null)
  let openBlocks = $state<Record<string, boolean>>({})

  const operatorChoices = $derived(availableOperatorSlugs($stats))
  const operatorOptions = $derived([
    { value: '', label: report ? `${report.operator} (detected)` : 'detected' },
    ...operatorChoices.map((slug) => ({ value: slug, label: slug })),
  ])

  /** Project state that can change what the prompt would contain. */
  const projectStateKey = $derived(
    [
      $stats?.cursor ?? '',
      $stats?.has_pending ?? '',
      ($stats?.effective_pins_at_cursor ?? []).join(','),
    ].join('|')
  )

  $effect(() => {
    if (!dialog) return
    if (request) {
      if (!dialog.open) dialog.showModal()
      return
    }
    if (dialog.open) dialog.close()
  })

  $effect(() => {
    const req = request
    if (!req) {
      report = null
      error = null
      return
    }
    // Re-read on every dependency below: the call is read-only (no transaction,
    // no model), so refetching whenever the project moves underneath is free.
    const params = {
      address: req.address,
      line: req.line,
      operator: operatorOverride || req.operator,
    }
    void projectStateKey
    void reloadSeq

    let cancelled = false
    loading = true
    error = null
    getExplain(params)
      .then((r) => {
        if (cancelled) return
        report = r
        // Collapsed by default: the bar plus block totals is the summary, and
        // drilling in is a deliberate move.
        openBlocks = {}
      })
      .catch((e: unknown) => {
        if (cancelled) return
        report = null
        error = e instanceof Error ? e.message : String(e)
      })
      .finally(() => {
        if (!cancelled) loading = false
      })

    return () => {
      cancelled = true
    }
  })

  const segments = $derived(report ? blockSegments(report, unit) : [])
  const total = $derived(report ? sizeOf(report.totals, unit) : 0)
  const altTotal = $derived(
    report ? formatSize(sizeOf(report.totals, unit === 'tokens' ? 'bytes' : 'tokens'), unit === 'tokens' ? 'bytes' : 'tokens') : ''
  )

  function handleClose() {
    explainRequest.set(null)
    operatorOverride = ''
    selectedBlock = null
  }

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === dialog) handleClose()
  }

  function selectBlock(blockId: string) {
    selectedBlock = blockId
    openBlocks = { ...openBlocks, [blockId]: true }
    document
      .getElementById(`explain-block-${blockId}`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  function toggleBlock(blockId: string, open: boolean) {
    if (openBlocks[blockId] === open) return
    openBlocks = { ...openBlocks, [blockId]: open }
  }

  function openKb(kbId: string) {
    const base = [$currentProject, $currentAddress || ''].filter(Boolean).join('/')
    window.location.hash = `${base}?kb=${encodeURIComponent(kbId)}`
    handleClose()
  }
</script>

<dialog
  bind:this={dialog}
  class="explain-dialog"
  data-testid="explain-modal"
  onclose={handleClose}
  onclick={handleBackdropClick}
>
  {#if request}
    <article class="explain-article">
      <header class="explain-header">
        <div class="explain-title-row">
          <strong data-testid="explain-title"
            >Context at {report ? reportHeadline(report) : (request.address ?? 'cursor')}</strong
          >
          <button type="button" class="explain-close" aria-label="Close" onclick={handleClose}>✕</button>
        </div>

        {#if report}
          <div class="explain-totals" data-testid="explain-totals">
            <span class="explain-total-value">{formatSize(total, unit)}</span>
            <span class="explain-total-alt">{altTotal}</span>
            <span class="explain-total-alt">{report.totals.messages} message{report.totals.messages === 1 ? '' : 's'}</span>
          </div>
        {/if}

        <div class="explain-controls">
          <div class="explain-unit" role="group" aria-label="Size unit">
            <button
              type="button"
              class={['explain-unit-btn', { active: unit === 'tokens' }]}
              aria-pressed={unit === 'tokens'}
              onclick={() => (unit = 'tokens')}>tokens</button
            >
            <button
              type="button"
              class={['explain-unit-btn', { active: unit === 'bytes' }]}
              aria-pressed={unit === 'bytes'}
              onclick={() => (unit = 'bytes')}>bytes</button
            >
          </div>

          <div class="explain-operator">
            <span>as</span>
            <SelectMenu
              ariaLabel="Assemble as operator"
              value={operatorOverride}
              options={operatorOptions}
              onChange={(v) => (operatorOverride = v)}
            />
          </div>

          <button
            type="button"
            class="explain-refresh"
            aria-label="Refresh"
            onclick={() => (reloadSeq += 1)}>⟳</button
          >
        </div>
      </header>

      <div class="explain-body">
        {#if error}
          <p class="explain-error" data-testid="explain-error">{error}</p>
        {:else if !report}
          <p class="explain-loading">Assembling…</p>
        {:else}
          <div class={['explain-content', { 'is-stale': loading }]}>
            <ExplainBar {segments} {unit} selected={selectedBlock} onSelect={selectBlock} />

            <div class="explain-blocks">
              {#each report.blocks as block (block.id)}
                <div id="explain-block-{block.id}">
                  <ExplainBlockSection
                    {block}
                    {report}
                    {unit}
                    open={openBlocks[block.id] ?? false}
                    onToggle={toggleBlock}
                    onOpenKb={openKb}
                  />
                </div>
              {/each}
            </div>

            <footer class="explain-footer">
              <p class="explain-cache-summary">
                About <strong>{formatShare(prefixShare(report, unit))}</strong> of this prompt is stable
                prefix — the part a prompt cache could reuse between calls. The split is a heuristic
                today, not a measurement from a provider.
              </p>

              {#if report.active_modalities.length > 0}
                <p class="explain-note">
                  Modalities: {report.active_modalities.join(', ')}
                </p>
              {/if}

              <p class="explain-note">
                Token counts are estimates at ~{report.chars_per_token} characters per token; byte
                counts are exact.
              </p>

              {#if report.excluded.length > 0 || report.warnings.length > 0}
                <details class="explain-warnings" data-testid="explain-warnings">
                  <summary
                    >{report.excluded.length + report.warnings.length} thing{report.excluded.length +
                      report.warnings.length ===
                    1
                      ? ''
                      : 's'} did not make it into the prompt</summary
                  >
                  <ul>
                    {#each report.excluded as item, i (`${item.id}:${i}`)}
                      <li><code>{item.id}</code> — {item.provenance}</li>
                    {/each}
                    {#each report.warnings as warning, i (`${i}:${warning}`)}
                      <li>{warning}</li>
                    {/each}
                  </ul>
                </details>
              {/if}
            </footer>
          </div>
        {/if}
      </div>
    </article>
  {/if}
</dialog>

<style>
  .explain-dialog::backdrop {
    background: rgba(0, 0, 0, 0.7);
  }

  .explain-article {
    margin: 0;
    display: flex;
    flex-direction: column;
    min-height: 0;
    max-height: 85vh;
  }

  .explain-header {
    padding: 0.75rem 1rem 0.6rem;
    border-bottom: 1px solid var(--pico-muted-border-color);
    flex-shrink: 0;
  }

  .explain-title-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .explain-title-row strong {
    word-break: break-word;
    font-size: 0.95rem;
  }

  .explain-close {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0.25rem 0.5rem;
    width: auto;
    margin: 0;
    color: var(--pico-muted-color);
    flex-shrink: 0;
  }

  .explain-close:hover {
    color: var(--pico-color);
  }

  .explain-totals {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-top: 0.35rem;
  }

  .explain-total-value {
    font-size: 1.5rem;
    line-height: 1.1;
  }

  .explain-total-alt {
    font-size: 0.78rem;
    color: var(--pico-muted-color);
  }

  .explain-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 0.55rem;
  }

  .explain-unit {
    display: flex;
    flex: 0 0 auto;
    gap: 2px;
  }

  .explain-unit-btn {
    flex: 0 0 auto;
    background: none;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 0.4rem;
    padding: 0.15rem 0.5rem;
    margin: 0;
    width: auto;
    min-height: 32px;
    font-size: 0.75rem;
    /* Pico redefines --pico-color inside `button`; inherit the article's ink. */
    color: inherit;
    cursor: pointer;
  }

  .explain-unit-btn.active {
    background: color-mix(in srgb, var(--pico-primary) 16%, transparent);
    border-color: var(--pico-primary);
  }

  .explain-operator {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    margin: 0;
    font-size: 0.75rem;
    color: var(--pico-muted-color);
  }

  .explain-operator :global(.select-menu-trigger) {
    min-width: 7rem;
    font-size: 0.75rem;
  }

  .explain-refresh {
    background: none;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 0.4rem;
    padding: 0.15rem 0.5rem;
    margin: 0 0 0 auto;
    width: auto;
    min-height: 32px;
    font-size: 0.85rem;
    color: inherit;
    cursor: pointer;
  }

  .explain-body {
    padding: 0.75rem 1rem 1rem;
    overflow-y: auto;
    overflow-x: hidden;
    flex: 1;
    min-height: 0;
  }

  .explain-content.is-stale {
    opacity: 0.6;
  }

  .explain-blocks {
    margin-top: 1rem;
  }

  .explain-error {
    color: var(--pico-del-color);
  }

  .explain-loading {
    color: var(--pico-muted-color);
  }

  .explain-footer {
    margin-top: 1rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--pico-muted-border-color);
  }

  .explain-cache-summary,
  .explain-note {
    font-size: 0.74rem;
    color: var(--pico-muted-color);
    margin: 0 0 0.4rem;
  }

  .explain-warnings {
    font-size: 0.74rem;
    color: var(--pico-muted-color);
  }

  .explain-warnings ul {
    margin: 0.3rem 0 0;
    padding-left: 1.1rem;
  }

  @media (max-width: 600px) {
    .explain-article {
      max-height: 92vh;
    }

    .explain-total-value {
      font-size: 1.25rem;
    }
  }
</style>
