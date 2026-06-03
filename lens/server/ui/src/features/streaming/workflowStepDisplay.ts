import type { WorkflowStepSnapshot } from '../../services/api'

/** Present-tense labels from the server are misleading once a step is skipped or done. */
export function workflowStepDisplayLabel(step: WorkflowStepSnapshot): string {
  const base = step.label.replace(/\u2026$/, '').trim()
  switch (step.status) {
    case 'skipped':
      return `${base} — skipped`
    case 'cancelled':
      return `${base} — cancelled`
    case 'success':
      return `${base} — done`
    default:
      return step.label
  }
}

export function workflowStepCancelLabel(step: WorkflowStepSnapshot): string {
  if (step.abort_rolls_back || step.id === 'auto_compress') {
    return 'Discard preview'
  }
  return 'Cancel'
}
