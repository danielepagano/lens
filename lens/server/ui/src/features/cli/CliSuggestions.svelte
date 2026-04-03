<script lang="ts">
  import type { Suggestion } from './CliAutocomplete'

  export let suggestions: Suggestion[] = []
  export let noWrap = false
  export let onSelect: (suggestion: Suggestion) => void = () => {}
  /** Runs on pointerdown before blur so the textarea selection is still valid. */
  export let onBeforeSelect: (() => void) | undefined = undefined
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
        class:cli-suggestion--dice-roll={sug.kind === 'dice-roll'}
        class:cli-suggestion--cursor-target-always={sug.cursorTargeting === 'always'}
        class:cli-suggestion--cursor-target-override={sug.cursorTargeting === 'can-override'}
        on:pointerdown={(e) => {
          onBeforeSelect?.()
          e.preventDefault()
        }}
        on:click={() => onSelect(sug)}
      >
        {#if sug.kind === 'dice-roll'}⚄ roll{:else}{sug.label}{/if}
      </button>
    {/each}
  </div>
{/if}
