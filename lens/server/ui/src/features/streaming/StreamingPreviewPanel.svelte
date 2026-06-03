<script lang="ts">
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
  const waitLabel = $derived(
    $streamingPreview?.statusLine ?? (isWaiting ? 'Waiting…' : 'Streaming…')
  )

  /** One-line hint from progress SSE or in-flight token preview (not a full log). */
  const activityLine = $derived.by(() => {
    const preview = $streamingPreview
    if (!preview) return null
    if (preview.statusLine?.trim()) return preview.statusLine.trim()
    if (activeStepId && preview.text.length > 0) return 'Writing to preview…'
    return null
  })

  async function handleCancelStep(_stepId: string) {
    try {
      await cancelStream()
    } catch (e) {
      console.error('Cancel failed:', e)
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
