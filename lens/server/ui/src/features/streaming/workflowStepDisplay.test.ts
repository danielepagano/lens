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
})
