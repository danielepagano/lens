<script lang="ts">
  import { onMount } from 'svelte'
  import type { Attachment } from 'svelte/attachments'
  import CommandBar from '../../components/CommandBar.svelte'
  import { guideModalCommand } from '../../stores/ui'
  import { committedWordCount } from './mediaSearchHandlers'

  type Props = {
    input?: string
    onSearch?: (query: string) => void
    onClear?: () => void
    onClose?: () => void
  }

  let {
    input = $bindable(''),
    onSearch = undefined,
    onClear = undefined,
    onClose = undefined,
  }: Props = $props()

  // Baseline for the whole-word-added/removed heuristic below; re-seeded on
  // every (re)mount so reopening a remembered query doesn't fire a spurious
  // search from a mismatched starting count. Nothing is "in progress" right
  // after a (re)mount, so every word counts as committed (cursorPos: -1).
  let prevCommitted = $state(committedWordCount(input, -1))

  let inputEl: HTMLTextAreaElement | null = null
  const attachInputEl: Attachment<HTMLTextAreaElement> = (element) => {
    inputEl = element
    return () => {
      if (inputEl === element) inputEl = null
    }
  }

  onMount(() => {
    inputEl?.focus()
    // Caret at the end, not the browser's default (start) — matters when
    // reopening with a remembered or folder-path-prefilled query so typing
    // continues the query rather than inserting into the middle of it.
    inputEl?.setSelectionRange(input.length, input.length)
  })

  function triggerSearch() {
    const trimmed = input.trim()
    if (trimmed) onSearch?.(trimmed)
    else onClear?.()
  }

  function handleInput(event: Event) {
    const target = event.currentTarget as HTMLTextAreaElement | null
    const cursorPos = target?.selectionStart ?? input.length
    const count = committedWordCount(input, cursorPos)
    if (count === prevCommitted) return
    prevCommitted = count
    triggerSearch()
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter' || event.shiftKey) return
    event.preventDefault()
    // Enter commits everything, including the word the cursor is on.
    prevCommitted = committedWordCount(input, -1)
    triggerSearch()
  }

  function openGuide() {
    guideModalCommand.set('media-search')
  }
</script>

<!-- Deliberately no `busy` prop: CommandInputField disables (and blurs) the
     textarea while busy, which would drop focus on every keystroke-triggered
     search. Loading state is shown in the results list instead. -->
<CommandBar
  bind:input
  leftButton={{ icon: '✕', label: 'Close search', ariaLabel: 'Close search', onClick: () => onClose?.() }}
  rightButton={{ icon: '?', label: 'Search guide', ariaLabel: 'Show search guide', onClick: openGuide }}
  attachInputEl={attachInputEl}
  inputId="lens-media-search"
  testId="media-search-input"
  onInput={handleInput}
  onKeydown={handleKeydown}
  autocapitalize="off"
  spellcheck={false}
/>
