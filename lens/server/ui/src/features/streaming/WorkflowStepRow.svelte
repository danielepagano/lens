<script lang="ts">
  import type { WorkflowStepSnapshot } from '../../services/api'
  import { workflowStepCancelLabel, workflowStepDisplayLabel } from './workflowStepDisplay'

  interface Props {
    step: WorkflowStepSnapshot
    isActive: boolean
    onSkip?: (stepId: string) => void
    onCancel?: (stepId: string) => void
  }

  let { step, isActive, onSkip, onCancel }: Props = $props()

  const displayLabel = $derived(workflowStepDisplayLabel(step))
  const cancelLabel = $derived(workflowStepCancelLabel(step))

  const statusIcon = $derived(
    step.status === 'success'
      ? '✓'
      : step.status === 'failed'
        ? '✗'
        : step.status === 'skipped' || step.status === 'cancelled'
          ? '–'
          : step.status === 'running' || isActive
            ? '●'
            : '○'
  )

  const canSkip = $derived(step.skippable === true && step.status === 'planned')
  const canCancel = $derived(
    isActive && step.status === 'running' && onCancel !== undefined
  )
  const showActiveStyle = $derived(
    (isActive || step.status === 'running') &&
      step.status !== 'skipped' &&
      step.status !== 'cancelled'
  )
</script>

<li
  class="workflow-step"
  class:workflow-step-active={showActiveStyle}
  class:workflow-step-skipped={step.status === 'skipped'}
  class:workflow-step-failed={step.status === 'failed'}
  class:workflow-step-success={step.status === 'success'}
  data-testid="workflow-step"
  data-step-id={step.id}
  data-step-status={step.status}
>
  <span class="workflow-step-icon" aria-hidden="true">{statusIcon}</span>
  <span class="workflow-step-label">{displayLabel}</span>
  {#if step.error && step.status === 'failed'}
    <span class="workflow-step-error">{step.error}</span>
  {/if}
  {#if (step.status === 'success' || step.status === 'skipped') && step.warnings?.length}
    <span class="workflow-step-warnings" data-testid="workflow-step-warnings">
      {step.warnings.join(' · ')}
    </span>
  {/if}
  <span class="workflow-step-actions">
    {#if canSkip && onSkip}
      <button
        type="button"
        class="workflow-step-skip secondary"
        data-testid="workflow-step-skip"
        aria-label="Skip {step.label.replace(/\u2026$/, '').trim()}"
        onclick={() => onSkip(step.id)}
      >
        Skip
      </button>
    {/if}
    {#if canCancel && onCancel}
      <button
        type="button"
        class="workflow-step-cancel secondary"
        data-testid="workflow-step-cancel"
        onclick={() => onCancel(step.id)}
      >
        {cancelLabel}
      </button>
    {/if}
  </span>
</li>
