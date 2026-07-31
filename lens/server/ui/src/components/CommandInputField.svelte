<script lang="ts">
  import type { Attachment } from 'svelte/attachments'
  import type { HTMLTextareaAttributes } from 'svelte/elements'

  type Props = {
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
    /** Distinguishes multiple concurrently-mounted CommandBar instances (e.g. the
     * main CLI bar vs. a feature-local search bar) — must stay unique per instance. */
    inputId?: string
    testId?: string
    onInput?: (event: Event) => void
    onKeydown?: (event: KeyboardEvent) => void
    onKeyup?: (event: KeyboardEvent) => void
    onSelectionRefresh?: () => void
    onBeforeInput?: (event: InputEvent) => void
    onFocus?: () => void
    onBlur?: (event: FocusEvent) => void
  }

  let {
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
    inputId = 'lens-cli',
    testId = 'cli-input',
    onInput = undefined,
    onKeydown = undefined,
    onKeyup = undefined,
    onSelectionRefresh = undefined,
    onBeforeInput = undefined,
    onFocus = undefined,
    onBlur = undefined,
  }: Props = $props()
</script>

<div class="cli-input-row">
  <div class="cli-input-wrapper">
    <textarea
      id={inputId}
      {@attach attachInputEl}
      class={['cli-input', { invalid: showInvalid, 'flash-invalid': flashInvalid }]}
      bind:value={input}
      oninput={onInput}
      onkeydown={onKeydown}
      onkeyup={onKeyup}
      onclick={onSelectionRefresh}
      onselect={onSelectionRefresh}
      onbeforeinput={onBeforeInput}
      onfocus={onFocus}
      onblur={onBlur}
      rows="1"
      disabled={busy}
      {autocomplete}
      {autocorrect}
      {autocapitalize}
      {spellcheck}
      data-testid={testId}
    ></textarea>
    {#if showHint}
      <div class="cli-input-ghost" aria-hidden="true">
        <span class="ghost-spacer">{input}</span>&nbsp;<span class="ghost-hint">{computedHint}</span>
      </div>
    {/if}
  </div>
  {#if busyMessage}
    <span class="cli-busy">{busyMessage}</span>
  {/if}
</div>
