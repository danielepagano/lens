<script lang="ts">
  import type { Suggestion } from './CliAutocomplete'

  export let suggestions: Suggestion[] = []
  export let noWrap = false
  export let onSelect: (suggestion: Suggestion) => void = () => {}
</script>

{#if suggestions.length > 0}
  <div class="cli-suggestions" class:no-wrap={noWrap}>
    {#each suggestions as sug}
      <button
        type="button"
        class="cli-suggestion"
        class:cli-suggestion--cli={sug.group === 'cli'}
        class:cli-suggestion--narrative={sug.group === 'narrative' && sug.kind !== 'flag' && sug.kind !== 'node'}
        class:cli-suggestion--opt-flag={sug.kind === 'flag'}
        class:cli-suggestion--node-suggest={sug.kind === 'node'}
        on:click={() => onSelect(sug)}
      >
        {sug.label}
      </button>
    {/each}
  </div>
{/if}
