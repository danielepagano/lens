<script lang="ts">
  import type { Suggestion } from './commandBarTypes'

  type Props = {
    suggestions?: Suggestion[]
    noWrap?: boolean
    onSelect?: (suggestion: Suggestion) => void
    // Runs on pointerdown before blur so the textarea selection is still valid.
    onBeforeSelect?: (() => void) | undefined
  }

  const NOOP_SELECT = (_suggestion: Suggestion) => {}

  let {
    suggestions = [],
    noWrap = false,
    onSelect = NOOP_SELECT,
    onBeforeSelect = undefined,
  }: Props = $props()

  function handleSuggestionPointerDown(event: PointerEvent) {
    onBeforeSelect?.()
    event.preventDefault()
  }
</script>

{#if suggestions.length > 0}
  <div class={['cli-suggestions', { 'no-wrap': noWrap }]}>
    {#each suggestions as sug (sug.value)}
      <button
        type="button"
        class={[
          'cli-suggestion',
          {
            'cli-suggestion--cli': sug.group === 'cli',
            'cli-suggestion--narrative': sug.group === 'narrative',
            'cli-suggestion--rpg': sug.group === 'rpg',
            'cli-suggestion--opt-flag': sug.kind === 'flag',
            'cli-suggestion--node-suggest': sug.kind === 'node',
            'cli-suggestion--prefix-group': sug.completionSuffix === '-',
            'cli-suggestion--media-dir': sug.isMountDirectory === true,
            'cli-suggestion--dice-roll': sug.kind === 'dice-roll',
            'cli-suggestion--var-mention':
              sug.kind === 'var-prefix' || sug.kind === 'var-key',
            'cli-suggestion--param-pin':
              sug.kind === 'flag' && sug.effectiveParamPin === true,
            'cli-suggestion--time-now': sug.kind === 'time-now',
            'cli-suggestion--go-cursor': sug.kind === 'go-cursor',
            'cli-suggestion--cursor-target-always':
              sug.cursorTargeting === 'always',
            'cli-suggestion--cursor-target-override':
              sug.cursorTargeting === 'can-override',
          },
        ]}
        onpointerdown={handleSuggestionPointerDown}
        onclick={() => onSelect(sug)}
      >
        {#if sug.kind === 'dice-roll'}⚄ roll{:else if sug.kind === 'time-now'}⏱ now{:else}{sug.label}{/if}
      </button>
    {/each}
  </div>
{/if}
