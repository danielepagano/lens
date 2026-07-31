<script lang="ts">
  import type { Snippet } from 'svelte'
  import type { Attachment } from 'svelte/attachments'
  import type { HTMLTextareaAttributes } from 'svelte/elements'
  import type { CommandBarButton, Suggestion } from './commandBarTypes'
  import CommandInputField from './CommandInputField.svelte'
  import CommandSuggestions from './CommandSuggestions.svelte'

  type Props = {
    suggestions?: Suggestion[]
    noWrapSuggestions?: boolean
    onSuggestionSelect?: (suggestion: Suggestion) => void
    // Runs on pointerdown before blur so the textarea selection is still valid.
    onSuggestionBeforeSelect?: (() => void) | undefined
    leftButton?: CommandBarButton | null
    rightButton?: CommandBarButton | null
    // Rendered above the input row (e.g. a history drawer); positioned
    // relative to the bar itself, matching the suggestion chips.
    overlay?: Snippet

    input?: string
    showInvalid?: boolean
    flashInvalid?: boolean
    busy?: boolean
    busyMessage?: string | null
    showHint?: boolean
    computedHint?: string
    autocomplete?: HTMLTextareaAttributes['autocomplete']
    autocorrect?: HTMLTextareaAttributes['autocorrect']
    autocapitalize?: HTMLTextareaAttributes['autocapitalize']
    spellcheck?: boolean
    attachInputEl?: Attachment<HTMLTextAreaElement>
    onInput?: (event: Event) => void
    onKeydown?: (event: KeyboardEvent) => void
    onKeyup?: (event: KeyboardEvent) => void
    onSelectionRefresh?: () => void
    onBeforeInput?: (event: InputEvent) => void
    onFocus?: () => void
    onBlur?: (event: FocusEvent) => void
  }

  let {
    suggestions = [],
    noWrapSuggestions = false,
    onSuggestionSelect = undefined,
    onSuggestionBeforeSelect = undefined,
    leftButton = null,
    rightButton = null,
    overlay = undefined,
    input = $bindable(''),
    showInvalid = false,
    flashInvalid = false,
    busy = false,
    busyMessage = null,
    showHint = false,
    computedHint = '',
    autocomplete = 'off',
    autocorrect = 'off',
    autocapitalize = 'off',
    spellcheck = false,
    attachInputEl = undefined,
    onInput = undefined,
    onKeydown = undefined,
    onKeyup = undefined,
    onSelectionRefresh = undefined,
    onBeforeInput = undefined,
    onFocus = undefined,
    onBlur = undefined,
  }: Props = $props()
</script>

<div class="bottom-bar" data-testid="bottom-bar">
  <CommandSuggestions
    {suggestions}
    noWrap={noWrapSuggestions}
    onBeforeSelect={onSuggestionBeforeSelect}
    onSelect={(suggestion) => onSuggestionSelect?.(suggestion)}
  />
  {@render overlay?.()}
  <div class="command-bar-row">
    {#if leftButton}
      <button
        type="button"
        class={['command-bar-btn', 'command-bar-btn--left', { active: leftButton.active }]}
        onclick={leftButton.onClick}
        aria-label={leftButton.ariaLabel ?? leftButton.label}
        title={leftButton.label}
      >{leftButton.icon}</button>
    {/if}
    <div class="command-bar-input-wrap">
      <CommandInputField
        bind:input
        {showInvalid}
        {flashInvalid}
        {busy}
        {busyMessage}
        {showHint}
        {computedHint}
        {autocomplete}
        {autocorrect}
        {autocapitalize}
        {spellcheck}
        {attachInputEl}
        {onInput}
        {onKeydown}
        {onKeyup}
        {onSelectionRefresh}
        {onBeforeInput}
        {onFocus}
        {onBlur}
      />
    </div>
    {#if rightButton}
      <button
        type="button"
        class={['command-bar-btn', 'command-bar-btn--right', { active: rightButton.active }]}
        onclick={rightButton.onClick}
        aria-label={rightButton.ariaLabel ?? rightButton.label}
        title={rightButton.label}
      >{rightButton.icon}</button>
    {/if}
  </div>
</div>

<style>
  .command-bar-row {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .command-bar-input-wrap {
    flex: 1;
    min-width: 0;
  }

  .command-bar-btn {
    flex-shrink: 0;
    background: none;
    border: 1px solid var(--pico-muted-border-color);
    font-size: 0.85rem;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    color: var(--pico-muted-color);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    transition: color 0.15s, border-color 0.15s;
  }

  .command-bar-btn--right {
    border-radius: 50%;
    width: 1.6rem;
    height: 1.6rem;
    margin-bottom: 0.3rem;
  }

  .command-bar-btn--left {
    margin-top: 0rem;
    margin-bottom: 0.4rem;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 4px;
  }

  .command-bar-btn:hover {
    color: var(--pico-color);
    border-color: var(--pico-color);
  }

  .command-bar-btn.active {
    color: var(--pico-color);
    border-color: var(--pico-color);
    background: var(--pico-muted-border-color);
  }
</style>
