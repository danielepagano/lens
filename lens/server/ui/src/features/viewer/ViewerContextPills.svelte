<script lang="ts">
  import type { Stats } from '../../services/api'
  import type { ParsedNodeHeader } from '../../utils/nodeHeaderBlock'
  import { explainRequest } from '../../stores/ui'

  type Props = {
    stats: Stats | null
    header: ParsedNodeHeader
    isCursorNode: boolean
    rememberPins: Record<string, string[]>
    /** Header row(s) vs cursor column (after markdown body). */
    placement?: 'header' | 'cursor'
    onOpenKb?: (id: string) => void
  }

  type KbPillRow = { id: string; unpin: boolean }
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

  /** One tooltip per pill, so the two decorations cannot fight over `title`. */
  function pinTitle(id: string): string | undefined {
    const lines: string[] = []
    if (pinIsState(id)) {
      lines.push('Live state — sent after the last turn, re-sent every beat')
    }
    const tags = rememberPins[id]
    if (tags && tags.length > 0) lines.push(...tags)
    return lines.length > 0 ? lines.join('\n') : undefined
  }

  function openKbItem(id: string) {
    onOpenKb?.(id)
  }

  /** Explain the cursor: no address means "wherever the cursor is right now". */
  function openContextReport() {
    explainRequest.set({})
  }

  function contextSummaryParts(
    pinCount: number,
    unpinCount: number,
    varCount: number,
    paramCount: number,
  ): string[] {
    const parts: string[] = []
    if (pinCount) parts.push(`${pinCount} pin${pinCount === 1 ? '' : 's'}`)
    if (unpinCount) parts.push(`${unpinCount} unpin${unpinCount === 1 ? '' : 's'}`)
    if (varCount) parts.push(`${varCount} var${varCount === 1 ? '' : 's'}`)
    if (paramCount) parts.push(`${paramCount} param${paramCount === 1 ? '' : 's'}`)
    return parts
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
    contextSummaryParts(
      header.pins.length,
      header.unpins.length,
      header.varsEntries.length,
      header.paramPills.length,
    ),
  )

  const cursorPins = $derived(stats?.effective_pins_at_cursor ?? [])
  const cursorVars = $derived(stats?.effective_vars_at_cursor ?? {})
  const cursorParams = $derived(stats?.effective_params_at_cursor ?? {})
  const cursorVarEntries = $derived(Object.entries(cursorVars).sort(([a], [b]) => a.localeCompare(b)))
  const cursorParamEntries = $derived(
    Object.entries(cursorParams).sort(([a], [b]) => a.localeCompare(b)),
  )
  const hasCursorRollup = $derived(
    isCursorNode &&
      (cursorPins.length > 0 ||
        cursorVarEntries.length > 0 ||
        cursorParamEntries.length > 0),
  )

  const cursorKbRows = $derived.by((): KbPillRow[] =>
    cursorPins.map((id) => ({ id, unpin: false as const })),
  )
  const cursorParamRows = $derived.by((): ParamPillRow[] =>
    cursorParamEntries.map(([pk, pv]) => ({ key: pk, label: `--${pk}=${pv}` })),
  )
  const cursorSummaryParts = $derived(
    contextSummaryParts(cursorPins.length, 0, cursorVarEntries.length, cursorParamEntries.length),
  )
</script>

{#snippet pillsBlock(
  kbRows: KbPillRow[],
  varEntries: [string, string][],
  paramRows: ParamPillRow[],
)}
  {#each kbRows as row, i (`${i}:${row.unpin ? `u:${row.id}` : row.id}`)}
    <button
      type="button"
      class={[
        'pin-pill',
        {
          'pin-pill-unpin': row.unpin,
          'pin-pill--remember': pinHasRememberTargets(row.id),
          'pin-pill--state': !row.unpin && pinIsState(row.id),
        },
      ]}
      title={pinTitle(row.id)}
      onclick={() => openKbItem(row.id)}
    >{row.unpin ? `-${row.id}` : row.id}</button>
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
  <div class="cursor-indicator-preview">
    <details class="cursor-pins-section" data-testid="cursor-context-rollups">
      <summary class="cursor-pins-summary">
        <span class="pins-count-label">{cursorSummaryParts.join(' · ')}</span>
      </summary>
      <div class="pin-pills effective-pins" data-testid="cursor-context-pills">
        {@render pillsBlock(cursorKbRows, cursorVarEntries, cursorParamRows)}
      </div>
    </details>
    {#if isCursorNode}{@render contextReportButton()}{/if}
  </div>
{:else if placement === 'cursor' && isCursorNode}
  <div class="cursor-indicator-preview">
    <span class="cursor-indicator">&gt;</span>
    {@render contextReportButton()}
  </div>
{/if}

<style>
  /* The rollup row is taller than its summary line, so centring in the flex
   * row drops the chip well below the "N pins" text it belongs to. Pin it to
   * the top of the row and nudge it onto the summary's own line instead. */
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
