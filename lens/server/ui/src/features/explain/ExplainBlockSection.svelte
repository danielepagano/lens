<script lang="ts">
  import type { ExplainBlock, ExplainReport } from '../../services/api'
  import {
    blockColorVar,
    cacheNote,
    componentRows,
    formatShare,
    formatSize,
    share,
    sizeOf,
    type ExplainUnit,
  } from './explainModel'

  type Props = {
    block: ExplainBlock
    report: ExplainReport
    unit: ExplainUnit
    open: boolean
    onToggle: (blockId: string, open: boolean) => void
    onOpenKb: (kbId: string) => void
  }

  let { block, report, unit, open, onToggle, onOpenKb }: Props = $props()

  const rows = $derived(componentRows(block, report, unit))
  const blockValue = $derived(sizeOf(block, unit))
  const blockShare = $derived(share(blockValue, sizeOf(report.totals, unit)))
  const colorVar = $derived(blockColorVar(block.id))
  // Framing is real cost but it belongs to the block, not to any component —
  // it is folded into the block total rather than drawn as a child row.
  const framing = $derived(unit === 'bytes' ? block.framing_bytes : block.framing_tokens)
</script>

<details
  class="explain-block"
  data-testid="explain-block"
  data-block={block.id}
  {open}
  ontoggle={(e) => onToggle(block.id, (e.currentTarget as HTMLDetailsElement).open)}
>
  <summary class="explain-block-summary">
    <span class="explain-swatch" style="background: var({colorVar});"></span>
    <span class="explain-block-label">{block.label}</span>
    <!-- Probably not needed
    <span class="explain-block-role" title="Message role this block is sent as">({block.role})</span>
    -->
    <span class="explain-block-value">{formatSize(blockValue, unit)}</span>
    <span class="explain-block-share">{formatShare(blockShare)}</span>
    <span class={['explain-cache', `explain-cache--${block.cache}`]} title={cacheNote(block.cache)}>
      {block.cache === 'prefix' ? 'cacheable' : 'volatile'}
    </span>
  </summary>

  <ul class="explain-rows">
    {#each rows as row (row.key)}
      <li class="explain-row" data-testid="explain-row">
        <div class="explain-row-head">
          <span class="explain-row-id">{row.id}</span>
          <span class="explain-row-value">{formatSize(row.value, unit)}</span>
          <span class="explain-row-share">{formatShare(row.shareOfTotal)}</span>
        </div>
        <div class="explain-row-track" aria-hidden="true">
          <span
            class="explain-row-fill"
            style="width: {Math.max(row.shareOfBlock, 1)}%; background: var({colorVar});"
          ></span>
        </div>
        <div class="explain-row-why">
          <span class="explain-row-provenance">{row.provenance}</span>
          {#if row.derived}
            <span class="explain-tag explain-tag--derived" title="Follows from another pin — remove what it derives from, not this."
              >derived</span
            >
          {/if}
          {#each row.tags as tag (tag)}
            <span class="explain-tag">{tag}</span>
          {/each}
          {#if row.kbId}
            <button type="button" class="explain-row-action" onclick={() => onOpenKb(row.kbId!)}
              >open KB</button
            >
          {/if}
        </div>
      </li>
    {/each}

    {#if framing > 0}
      <li class="explain-row explain-row--framing">
        <div class="explain-row-head">
          <span class="explain-row-id">block framing</span>
          <span class="explain-row-value">{formatSize(framing, unit)}</span>
          <span class="explain-row-share"></span>
        </div>
        <div class="explain-row-why">
          <span class="explain-row-provenance">block header/footer and separators</span>
        </div>
      </li>
    {/if}
  </ul>
</details>

<style>
  .explain-block {
    border-top: 1px solid var(--pico-muted-border-color);
  }

  .explain-block-summary {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.5rem 0;
    min-height: 36px;
    cursor: pointer;
    font-size: 0.82rem;
  }

  .explain-swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .explain-block-label {
    font-weight: 600;
    letter-spacing: 0.02em;
  }

  .explain-block-role {
    color: var(--pico-muted-color);
    font-size: 0.72rem;
  }

  .explain-block-value,
  .explain-block-share {
    margin-left: auto;
    font-variant-numeric: tabular-nums;
    color: var(--pico-muted-color);
  }

  .explain-block-share {
    margin-left: 0;
    min-width: 3.2rem;
    text-align: right;
  }

  .explain-cache {
    font-size: 0.68rem;
    border-radius: 0.4rem;
    padding: 0.05rem 0.35rem;
    border: 1px solid var(--pico-muted-border-color);
    color: var(--pico-muted-color);
    white-space: nowrap;
  }

  .explain-cache--prefix {
    border-color: color-mix(in srgb, var(--pico-primary) 45%, transparent);
  }

  .explain-rows {
    list-style: none;
    margin: 0 0 0.5rem;
    padding: 0;
  }

  .explain-row {
    padding: 0.35rem 0 0.35rem 1.15rem;
    list-style: none;
  }

  .explain-row-head {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.8rem;
  }

  .explain-row-id {
    font-family: var(--pico-font-family-monospace, monospace);
    word-break: break-all;
  }

  .explain-row-value,
  .explain-row-share {
    margin-left: auto;
    color: var(--pico-muted-color);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .explain-row-share {
    margin-left: 0;
    min-width: 3.2rem;
    text-align: right;
  }

  .explain-row-track {
    height: 4px;
    margin: 0.25rem 0;
    background: var(--pico-muted-border-color);
    border-radius: 2px;
    overflow: hidden;
  }

  .explain-row-fill {
    display: block;
    height: 100%;
    border-radius: 2px;
  }

  .explain-row-why {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.72rem;
    color: var(--pico-muted-color);
  }

  .explain-tag {
    border: 1px solid var(--pico-muted-border-color);
    border-radius: 0.4rem;
    padding: 0 0.3rem;
    font-size: 0.68rem;
  }

  .explain-tag--derived {
    font-style: italic;
  }

  .explain-row-action {
    background: none;
    border: none;
    padding: 0.15rem 0.25rem;
    margin: 0;
    width: auto;
    font-size: 0.72rem;
    color: var(--pico-primary);
    text-decoration: underline;
    cursor: pointer;
  }

  .explain-row--framing .explain-row-id {
    font-style: italic;
    color: var(--pico-muted-color);
  }
</style>
