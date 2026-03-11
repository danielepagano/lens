<script lang="ts">
  import { runCliStream, cancelCliRun, CliRunBusyError } from '../services/api'
  import { cliOutput, treeRefreshTrigger } from '../stores/ui'

  const MAX_HISTORY = 50

  export let onCliDone: (() => Promise<void>) | undefined = undefined

  let input = ''
  let busy = false
  let busyMessage: string | null = null
  let cliInputEl: HTMLTextAreaElement | null = null
  let history: string[] = []
  let historyIndex = -1

  function focusCliInput() {
    setTimeout(() => {
      if (!cliInputEl) return
      try {
        cliInputEl.focus({ preventScroll: true })
      } catch {
        cliInputEl.focus()
      }
    }, 0)
  }

  function pushHistory(command: string) {
    if (!command) return
    history = [...history, command].slice(-MAX_HISTORY)
    historyIndex = -1
  }

  function handleKeydown(e: KeyboardEvent) {
    const isTouchDevice =
      typeof window !== 'undefined' && 'ontouchstart' in window

    if (input.trim() === '') {
      if (e.key === 'Enter' && !e.shiftKey) {
        // Empty Enter: do not send a command.
        // On touch devices, treat this as a dismiss gesture.
        e.preventDefault()
        if (isTouchDevice) {
          cliInputEl?.blur()
        }
        return
      }

      if (e.key === 'Backspace') {
        // On touch devices, Backspace on an empty CLI acts as a dismiss gesture.
        if (isTouchDevice) {
          e.preventDefault()
          cliInputEl?.blur()
          return
        }
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (history.length === 0) return
      if (historyIndex === -1) {
        historyIndex = history.length - 1
        input = history[historyIndex] ?? ''
      } else if (historyIndex > 0) {
        historyIndex--
        input = history[historyIndex] ?? ''
      }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (historyIndex === -1) return
      if (historyIndex < history.length - 1) {
        historyIndex++
        input = history[historyIndex] ?? ''
      } else {
        historyIndex = -1
        input = ''
      }
    }
  }

  function handleBeforeInput(e: InputEvent) {
    // Mobile keyboards often emit line breaks via beforeinput rather than keydown.
    if (busy) return
    if (e.isComposing) return
    if (e.inputType === 'insertLineBreak' || e.inputType === 'insertParagraph') {
      e.preventDefault()
      submit()
    }
  }

  async function submit() {
    const command = input.trim()
    if (command === '') {
      // Do not run or add empty commands to history.
      if (typeof window !== 'undefined' && 'ontouchstart' in window) {
        cliInputEl?.blur()
      }
      return
    }

    pushHistory(command)
    busy = true
    busyMessage = null
    cliOutput.set({ output: '', exitCode: null, streaming: true })

    try {
      await runCliStream(command, (event) => {
        if (event.type === 'out' || event.type === 'err') {
          cliOutput.update((p) =>
            p ? { ...p, output: p.output + (event.text ?? '') } : p
          )
        } else if (event.type === 'done') {
          cliOutput.update((p) =>
            p
              ? {
                  ...p,
                  exitCode: event.exit_code ?? null,
                  streaming: false,
                }
              : p
          )
        }
      })
      if (onCliDone) await onCliDone()
      treeRefreshTrigger.update((n) => n + 1)
      input = ''
    } catch (err) {
      if (err instanceof CliRunBusyError) {
        busyMessage = err.message
        cliOutput.update((p) =>
          p
            ? { ...p, output: p.output + err.message + '\n', streaming: false }
            : p
        )
      } else {
        cliOutput.update((p) =>
          p
            ? {
                ...p,
                output: p.output + (err instanceof Error ? err.message : String(err)),
                exitCode: 1,
                streaming: false,
              }
            : p
        )
        if (onCliDone) await onCliDone()
        input = ''
      }
    } finally {
      busy = false
      // Keep focusing after a run for quick desktop workflows; on mobile
      // Safari this uses preventScroll to avoid jumping the viewport.
      focusCliInput()
    }
  }
</script>

<div class="bottom-bar" data-testid="bottom-bar">
  <div class="cli-input-row">
    <textarea
      bind:this={cliInputEl}
      class="cli-input"
      bind:value={input}
      on:keydown={handleKeydown}
      on:beforeinput={handleBeforeInput}
      placeholder="lens CLI"
      rows="1"
      disabled={busy}
      data-testid="cli-input"
    />
    {#if busyMessage}
      <span class="cli-busy">{busyMessage}</span>
    {/if}
  </div>
</div>
