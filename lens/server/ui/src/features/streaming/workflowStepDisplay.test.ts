import { describe, expect, it } from 'vitest'
import { workflowStepCancelLabel, workflowStepDisplayLabel } from './workflowStepDisplay'

describe('workflowStepDisplayLabel', () => {
  it('marks skipped auto-compress without present-tense wording', () => {
    expect(
      workflowStepDisplayLabel({
        id: 'auto_compress',
        label: 'Auto-compressing…',
        status: 'skipped',
      })
    ).toBe('Auto-compressing — skipped')
  })

  it('keeps running labels unchanged', () => {
    expect(
      workflowStepDisplayLabel({
        id: 'generate',
        label: 'Generating (write)…',
        status: 'running',
      })
    ).toBe('Generating (write)…')
  })
})

describe('workflowStepCancelLabel', () => {
  it('uses discard for auto-compress', () => {
    expect(
      workflowStepCancelLabel({
        id: 'auto_compress',
        label: 'Auto-compressing…',
        status: 'running',
      })
    ).toBe('Discard preview')
  })

  it('reads as a skip for step-scoped steps, which keep the generated text', () => {
    expect(
      workflowStepCancelLabel({
        id: 'workflow_refine:speech_markup',
        label: 'Refining (speech markup)…',
        status: 'running',
        cancel_scope: 'step',
      })
    ).toBe('Skip')
  })

  it('prefers the step-supplied label, which names what survives', () => {
    expect(
      workflowStepCancelLabel({
        id: 'remember',
        label: 'Updating memory…',
        status: 'running',
        cancel_scope: 'step',
        cancel_label: 'Skip memory',
      })
    ).toBe('Skip memory')
  })

  it('cancels the stream for workflow-scoped steps', () => {
    expect(
      workflowStepCancelLabel({
        id: 'generate',
        label: 'Generating (write)…',
        status: 'running',
      })
    ).toBe('Cancel')
  })
})
