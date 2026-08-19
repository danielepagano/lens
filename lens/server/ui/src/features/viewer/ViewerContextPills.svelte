<script lang="ts">
  import type { Stats } from '../../services/api'
  import type { ParsedNodeHeader } from '../../utils/nodeHeaderBlock'
  import { explainRequest } from '../../stores/ui'
  import {
    contextSummaryParts,
    cursorKbRows as buildCursorKbRows,
    pillKey,
    pillLabel,
    pillTitle,
    splitPillRows,
    type KbPillRow,
  } from './contextPillRows'

  type Props = {
    stats: Stats | null
    header: ParsedNodeHeader
    isCursorNode: boolean
    rememberPins: Record<string, string[]>
    /** Header row(s) vs cursor column (after markdown body). */
    placement?: 'header' | 'cursor'
    onOpenKb?: (id: string) => void
  }

  type ParamPillRow = { key: string; label: string }

  let {
    stats,
    header,
    isCursorNode,
    rememberPins,
    placement = 'header',
    onOpenKb,
  }: Props = $props()

  function pinHasRememberTargets(id: string): boolean {
    return Boolean(rememberPins[id]?.length)
  }

  /** Tagged `state`: rendered at the prompt tail and re-sent on every beat. */
  const statePins = $derived(new Set(stats?.state_pins_at_cursor ?? []))

  function pinIsState(id: string): boolean {
    return statePins.has(id)
  }

  function pinTitle(row: KbPillRow): string | undefined {
    return pillTitle(row, {
      isState: pinIsState,
      rememberTags: (id) => rememberPins[id] ?? [],
    })
  }

  function openKbItem(id: string) {
    onOpenKb?.(id)
  }

  /** Explain the cursor: no address means "wherever the cursor is right now". */
  function openContextReport() {
    explainRequest.set({})
  }

  const hasHeaderKb = $derived(header.pins.length > 0 || header.unpins.length > 0)
  const hasHeaderVars = $derived(header.varsEntries.length > 0)
  const hasHeaderParams = $derived(header.paramPills.length > 0)
  const hasHeaderRollup = $derived(hasHeaderKb || hasHeaderVars || hasHeaderParams)

  const headerKbRows = $derived.by((): KbPillRow[] => [
    ...header.pins.map((id) => ({ id, unpin: false as const })),
    ...header.unpins.map((id) => ({ id, unpin: true as const })),
  ])
  const headerParamRows = $derived.by((): ParamPillRow[] =>
    header.paramPills.map((p) => ({
      key: `${p.scope}:${p.name}`,
      label: `--${p.scope}:${p.name}=${p.value}`,
    })),
  )
  const headerSummaryParts = $derived(
    contextSummaryParts({
      pins: header.pins.length,
      unpins: header.unpins.length,
      vars: header.varsEntries.length,
      params: header.paramPills.length,
    }),
  )

  const cursorPins = $derived(stats?.effective_pins_at_cursor ?? [])
  /** Node-local scope, listed after the pins it does not behave like. */
  const cursorIncludes = $derived(stats?.include_ids_at_cursor ?? [])
  const cursorMentions = $derived(stats?.mention_ids_at_cursor ?? [])
  const cursorVars = $derived(stats?.effective_vars_at_cursor ?? {})
  const cursorParams = $derived(stats?.effective_params_at_cursor ?? {})
  const cursorVarEntries = $derived(Object.entries(cursorVars).sort(([a], [b]) => a.localeCompare(b)))
  const cursorParamEntries = $derived(
    Object.entries(cursorParams).sort(([a], [b]) => a.localeCompare(b)),
  )
  const hasCursorRollup = $derived(
    isCursorNode &&
      (cursorPins.length > 0 ||
        cursorIncludes.length > 0 ||
        cursorMentions.length > 0 ||
        cursorVarEntries.length > 0 ||
        cursorParamEntries.length > 0),
  )

  const cursorKbRows = $derived(
    buildCursorKbRows(cursorPins, cursorIncludes, cursorMentions),
  )
  /** Plain ancestor pins stay behind the summary; includes, mentions, and
   * `state`-tagged pins are notable and few, so show them without a click. */
  const cursorSplitRows = $derived(splitPillRows(cursorKbRows, pinIsState))
  const cursorParamRows = $derived.by((): ParamPillRow[] =>
    cursorParamEntries.map(([pk, pv]) => ({ key: pk, label: `--${pk}=${pv}` })),
  )
  const cursorSummaryParts = $derived(
    contextSummaryParts({
      pins: cursorPins.length,
      vars: cursorVarEntries.length,
      params: cursorParamEntries.length,
      includes: cursorIncludes.length,
      mentions: cursorMentions.length,
    }),
  )
</script>

{#snippet pillsBlock(
  kbRows: KbPillRow[],
  varEntries: [string, string][],
  paramRows: ParamPillRow[],
)}
  {#each kbRows as row, i (pillKey(row, i))}
    <button
      type="button"
      class={[
        'pin-pill',
        {
          'pin-pill-unpin': row.unpin,
          'pin-pill--scoped': Boolean(row.scope),
          'pin-pill--remember': pinHasRememberTargets(row.id),
          'pin-pill--state': !row.unpin && pinIsState(row.id),
        },
      ]}
      title={pinTitle(row)}
      onclick={() => openKbItem(row.id)}
    >{pillLabel(row)}</button>
  {/each}
  {#each varEntries as [k, v] (`${k}=${v}`)}
    <span class="pin-pill pin-pill-var">@var:{k}={v}</span>
  {/each}
  {#each paramRows as p (p.key)}
    <span class="pin-pill pin-pill-param">{p.label}</span>
  {/each}
{/snippet}

{#if placement === 'header' && hasHeaderRollup}
  <div
    class="cursor-indicator-preview viewer-header-context viewer-header-context--rollup"
    data-testid="viewer-header-context"
  >
    <details class="cursor-pins-section" data-testid="viewer-header-context-rollups">
      <summary class="cursor-pins-summary node-header-context-summary">
        <span class="pins-count-label">{headerSummaryParts.join(' · ')}</span>
      </summary>
      <div class="pin-pills effective-pins" data-testid="viewer-header-context-pills">
        {@render pillsBlock(headerKbRows, header.varsEntries, headerParamRows)}
      </div>
    </details>
  </div>
{/if}

{#snippet contextReportButton()}
  <button
    type="button"
    class="context-report-btn"
    title="What is in the prompt here, how big, and why"
    data-testid="cursor-context-explain"
    onclick={openContextReport}>context</button
  >
{/snippet}

{#if placement === 'cursor' && hasCursorRollup}
  <div class="cursor-indicator-preview cursor-context-stack">
    <div class="cursor-context-row">
      <details class="cursor-pins-section" data-testid="cursor-context-rollups">
        <summary class="cursor-pins-summary">
          <span class="pins-count-label">{cursorSummaryParts.join(' · ')}</span>
        </summary>
        <div class="pin-pills effective-pins" data-testid="cursor-context-pills">
          {@render pillsBlock(cursorSplitRows.plain, cursorVarEntries, cursorParamRows)}
        </div>
      </details>
      {#if isCursorNode}{@render contextReportButton()}{/if}
    </div>
    {#if cursorSplitRows.notable.length > 0}
      <div class="pin-pills effective-pins notable-pins" data-testid="cursor-context-notable-pills">
        {@render pillsBlock(cursorSplitRows.notable, [], [])}
      </div>
    {/if}
  </div>
{:else if placement === 'cursor' && isCursorNode}
  <div class="cursor-indicator-preview">
    <span class="cursor-indicator">&gt;</span>
    {@render contextReportButton()}
  </div>
{/if}

<style>
  /* The pins disclosure and the notable (include/mention/state) pills are two
   * different rhythms — one static and collapsible, one small and always
   * shown — so they get their own row each instead of fighting for space in
   * one flex line. */
  .cursor-context-stack {
    flex-direction: column;
    align-items: stretch;
    gap: 0.25rem;
  }

  .cursor-context-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .context-report-btn {
    align-self: flex-start;
    background: none;
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 0.5rem;
    padding: 0.05rem 0.35rem;
    margin: 0.15rem 0 0 0.4rem;
    width: auto;
    font-size: 0.7rem;
    font-family: inherit;
    line-height: 1.4;
    color: var(--pico-muted-color);
    cursor: pointer;
  }

  .context-report-btn:hover {
    color: var(--pico-color);
    border-color: var(--pico-primary);
  }
</style>
