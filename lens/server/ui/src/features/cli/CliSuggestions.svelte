<script lang="ts">
  import type { Suggestion } from './CliAutocomplete'

  export let suggestions: Suggestion[] = []
  export let noWrap = false
  export let onSelect: (suggestion: Suggestion) => void = () => {}
</script>

{#if suggestions.length > 0}
  <div class="cli-suggestions" class:no-wrap={noWrap}>
    {#each suggestions as sug (sug.value)}
      <button
        type="button"
        class="cli-suggestion"
        class:cli-suggestion--cli={sug.group === 'cli'}
        class:cli-suggestion--narrative={sug.group === 'narrative'}
        class:cli-suggestion--rpg={sug.group === 'rpg'}
        class:cli-suggestion--opt-flag={sug.kind === 'flag'}
        class:cli-suggestion--node-suggest={sug.kind === 'node'}
        class:cli-suggestion--prefix-group={sug.completionSuffix === '-'}
        class:cli-suggestion--media-dir={sug.isMountDirectory === true}
        on:pointerdown|preventDefault
        on:click={() => onSelect(sug)}
      >
        {sug.label}
      </button>
    {/each}
  </div>
{/if}
