<script lang="ts">
  import { onMount } from 'svelte'
  import { streamingPreview } from '../../stores/document'
  import { cancelStream, workflowStreamAction } from '../../services/api'
  import WorkflowStepRow from './WorkflowStepRow.svelte'

  const isOpen = $derived($streamingPreview !== null)
  const steps = $derived($streamingPreview?.steps ?? [])
  const hasSteps = $derived(steps.length > 0)
  const pausedStepId = $derived($streamingPreview?.pausedStepId)
  const activeStepId = $derived($streamingPreview?.activeStepId)
  const isWaiting = $derived(
    $streamingPreview !== null && $streamingPreview.text === '' && !hasSteps
  )

  // Coarse "now" clock — approximate rate/elapsed only need to refresh every ~1s,
  // not on every token, so this is decoupled from the store's own update cadence.
  let nowMs = $state(Date.now())
  onMount(() => {
    const id = window.setInterval(() => {
      nowMs = Date.now()
    }, 1000)
    return () => window.clearInterval(id)
  })

  /** "≈340 tok · 42/s · turn 3" — approximate, from streamed byte count; omitted until there's enough to show. */
  const statsSuffix = $derived.by(() => {
    const preview = $streamingPreview
    if (!preview) return null
    const totalBytes = new TextEncoder().encode(preview.text).length + (preview.hiddenBytes ?? 0)
    const approxTokens = Math.round(totalBytes / 4)
    if (approxTokens < 1) return null
    const elapsedSec = Math.max(1, (nowMs - (preview.streamStartedAt ?? nowMs)) / 1000)
    const rate = approxTokens / elapsedSec
    const tokenLabel = approxTokens >= 1000 ? `${(approxTokens / 1000).toFixed(1)}k` : `${approxTokens}`
    const parts = [`≈${tokenLabel} tok`, `${rate.toFixed(rate < 10 ? 1 : 0)}/s`]
    if ((preview.turnCount ?? 1) > 1) parts.push(`turn ${preview.turnCount}`)
    return parts.join(' · ')
  })

  const waitLabel = $derived.by(() => {
    const base = $streamingPreview?.statusLine ?? (isWaiting ? 'Waiting…' : 'Streaming…')
    return statsSuffix ? `${base} · ${statsSuffix}` : base
  })

  /** One-line hint from progress SSE or in-flight token preview (not a full log). */
  const activityLine = $derived.by(() => {
    const preview = $streamingPreview
    if (!preview) return null
    let base: string | null = null
    if (preview.statusLine?.trim()) base = preview.statusLine.trim()
    else if (activeStepId && preview.text.length > 0) base = 'Writing to preview…'
    if (!base) return statsSuffix
    return statsSuffix ? `${base} · ${statsSuffix}` : base
  })

  /** Step-scoped steps (refine) stop alone and keep their input; everything else aborts the stream. */
  async function handleCancelStep(stepId: string) {
    const step = steps.find((s) => s.id === stepId)
    const stepScoped = step?.cancel_scope === 'step'
    try {
      if (stepScoped) {
        await workflowStreamAction(stepId, 'cancel')
      } else {
        await cancelStream()
      }
    } catch (e) {
      // A silent no-op here looks identical to "the button does nothing", so say so.
      const detail = e instanceof Error ? e.message : String(e)
      console.error('Cancel failed:', e)
      streamingPreview.update((prev) =>
        prev
          ? { ...prev, statusLine: `${stepScoped ? 'Skip' : 'Cancel'} failed: ${detail}` }
          : prev
      )
    }
  }

  async function handleWorkflowAction(stepId: string, action: 'retry' | 'skip') {
    if (action === 'skip') {
      streamingPreview.update((prev) =>
        prev
          ? {
              ...prev,
              steps: prev.steps.map((s) =>
                s.id === stepId ? { ...s, status: 'skipped' as const } : s
              ),
              pausedStepId: undefined,
            }
          : prev
      )
    }
    try {
      await workflowStreamAction(stepId, action)
      if (action === 'retry') {
        streamingPreview.update((prev) =>
          prev ? { ...prev, pausedStepId: undefined } : prev
        )
      }
    } catch (e) {
      if (action === 'skip') {
        streamingPreview.update((prev) =>
          prev
            ? {
                ...prev,
                steps: prev.steps.map((s) =>
                  s.id === stepId && s.status === 'skipped'
                    ? { ...s, status: 'planned' as const }
                    : s
                ),
              }
            : prev
        )
      }
      console.error('Workflow action failed:', e)
    }
  }

  function handleDismiss() {
    streamingPreview.set(null)
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!isOpen) return
    if (e.key === 'Escape' && !pausedStepId) {
      e.preventDefault()
      if (hasSteps && activeStepId) {
        void handleCancelStep(activeStepId)
      } else if (!hasSteps) {
        void handleCancelStep('')
      }
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if isOpen}
  <div class="streaming-panel" data-testid="streaming-panel">
    {#if hasSteps}
      <ul class="workflow-steps" data-testid="workflow-steps">
        {#each steps as step (step.id)}
          <WorkflowStepRow
            {step}
            isActive={step.id === activeStepId}
            onSkip={(stepId) => handleWorkflowAction(stepId, 'skip')}
            onCancel={handleCancelStep}
          />
        {/each}
      </ul>
      {#if activityLine}
        <p class="workflow-activity" data-testid="workflow-activity" title={activityLine}>
          {activityLine}
        </p>
      {/if}
    {:else}
      <span class="streaming-label">{waitLabel}</span>
    {/if}

    <div class="streaming-panel-actions">
      {#if pausedStepId}
        <button
          type="button"
          class="streaming-action-btn"
          data-testid="workflow-retry"
          onclick={() => handleWorkflowAction(pausedStepId!, 'retry')}
        >
          Retry
        </button>
        <button
          type="button"
          class="streaming-action-btn secondary"
          data-testid="workflow-skip"
          onclick={() => handleWorkflowAction(pausedStepId!, 'skip')}
        >
          Skip
        </button>
      {/if}
      {#if $streamingPreview?.sticky && !pausedStepId}
        <button
          type="button"
          class="streaming-action-btn secondary"
          data-testid="workflow-dismiss"
          onclick={handleDismiss}
        >
          Dismiss
        </button>
      {/if}
      {#if !hasSteps}
        <button
          type="button"
          class="streaming-cancel-btn"
          onclick={() => handleCancelStep('')}
          aria-label="Cancel streaming"
        >
          Cancel
        </button>
      {/if}
    </div>
  </div>
{/if}
