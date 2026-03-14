import { describe, it, expect } from 'vitest'
import {
  buildNodeTransactionOverlay,
  preprocessAnnotations,
  type NodeTransactionOverlay,
  type RemovedGroup,
} from './markdown'
import type { TransactionState, FileDiff, DiffHunk, DiffLine } from '../services/api'

function makeTransaction(
  address: string,
  hunks: DiffHunk[],
): TransactionState {
  return {
    has_pending: true,
    owner: `${address}#edit:test`,
    is_mutation: true,
    files: [{ path: `narrative/${address}/_node.md`, address, hunks }],
  }
}

function makeHunk(
  oldStart: number,
  newStart: number,
  lines: DiffLine[],
): DiffHunk {
  return { old_start: oldStart, new_start: newStart, lines }
}

function addLine(text: string, isAnnotation = false): DiffLine {
  return { kind: 'add', text, is_annotation: isAnnotation }
}

function removeLine(text: string, isAnnotation = false): DiffLine {
  return { kind: 'remove', text, is_annotation: isAnnotation }
}

function contextLine(text: string): DiffLine {
  return { kind: 'context', text, is_annotation: false }
}

describe('buildNodeTransactionOverlay', () => {
  it('returns null when transaction has no pending changes', () => {
    const tx: TransactionState = {
      has_pending: false,
      owner: null,
      is_mutation: false,
      files: [],
    }
    const result = buildNodeTransactionOverlay(tx, 'some/address')
    expect(result).toBeNull()
  })

  it('returns null when address does not match any file', () => {
    const tx = makeTransaction('other/address', [])
    const result = buildNodeTransactionOverlay(tx, 'some/address')
    expect(result).toBeNull()
  })

  it('returns null when there are no changes (empty hunks)', () => {
    const tx = makeTransaction('test/node', [])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).toBeNull()
  })

  it('tracks added line numbers correctly', () => {
    const tx = makeTransaction('test/node', [
      makeHunk(1, 1, [
        addLine('first added line'),
        addLine('second added line'),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.addedLines).toEqual(new Set([1, 2]))
  })

  it('skips annotation lines when tracking added lines', () => {
    const tx = makeTransaction('test/node', [
      makeHunk(1, 1, [
        addLine('[write]: #', true),
        addLine('actual content'),
        addLine('[/write]: #', true),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    // Line 1 is annotation (skipped), line 2 is content, line 3 is annotation (skipped)
    expect(result!.addedLines).toEqual(new Set([2]))
  })

  it('tracks removed groups with correct beforeLine', () => {
    const tx = makeTransaction('test/node', [
      makeHunk(5, 5, [
        removeLine('old content'),
        addLine('new content'),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0]).toEqual({
      beforeLine: 5,
      lines: ['old content'],
    })
  })

  it('groups consecutive removed lines together', () => {
    const tx = makeTransaction('test/node', [
      makeHunk(5, 5, [
        removeLine('line one'),
        removeLine('line two'),
        removeLine('line three'),
        addLine('replacement'),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0].lines).toEqual([
      'line one',
      'line two',
      'line three',
    ])
  })

  it('skips annotation lines in removed groups', () => {
    const tx = makeTransaction('test/node', [
      makeHunk(5, 5, [
        removeLine('[edit:e1_2', true),
        removeLine('  prompt: test', true),
        removeLine(']: #', true),
        removeLine(''),
        removeLine('actual removed content'),
        removeLine(''),
        removeLine('[/edit:e1_2]: #', true),
        addLine('REPLACEMENT'),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    // Should only include non-annotation lines
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0].lines).toEqual([
      '',
      'actual removed content',
      '',
    ])
  })

  it('handles mutation with new_start offset', () => {
    // Simulates an edit where claim tags push content to a different line
    const tx = makeTransaction('test/node', [
      makeHunk(8, 5, [
        removeLine('[edit:e8_9', true),
        removeLine('  manual: true', true),
        removeLine('  prompt: new text', true),
        removeLine(']: #', true),
        removeLine(''),
        removeLine('original paragraph'),
        removeLine(''),
        removeLine('[/edit:e8_9]: #', true),
        addLine('new text'),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    // Added line should be at new_start (5), not old_start (8)
    expect(result!.addedLines).toEqual(new Set([5]))
    expect(result!.removedGroups[0].beforeLine).toBe(5)
  })

  it('handles trailing removed lines (no add after removes)', () => {
    const tx = makeTransaction('test/node', [
      makeHunk(5, 5, [
        removeLine('deleted line one'),
        removeLine('deleted line two'),
      ]),
    ])
    const result = buildNodeTransactionOverlay(tx, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.addedLines.size).toBe(0)
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0]).toEqual({
      beforeLine: 5,
      lines: ['deleted line one', 'deleted line two'],
    })
  })
})

describe('preprocessAnnotations with overlay', () => {
  it('correctly identifies added line when context lines precede changes', () => {
    // Simulates the edit mutation case:
    // - Diff starts at new_start: 5 (first context line)
    // - But there are 3 context lines before the actual change
    // - So "REPLACED TEXT" is actually at line 8, not line 5
    const markdown = `Line 1
Line 2
[section:s1]: #

Carlos sleeps peacefully
  
[/section:s1]: #
REPLACED TEXT

[write]: #

More content`

    // Transaction from backend - NOW includes context lines
    const tx: TransactionState = {
      has_pending: true,
      owner: 'test#edit:e1',
      is_mutation: true,
      files: [{
        path: 'test/_node.md',
        address: 'test/node',
        hunks: [{
          old_start: 5,
          new_start: 5,
          lines: [
            // Context lines (new lines 5, 6, 7):
            contextLine('Carlos sleeps peacefully'),
            contextLine('  '),
            contextLine('[/section:s1]: #'),
            // Removed lines (don't increment new line counter):
            removeLine('[edit:e1', true),
            removeLine('  prompt: test', true),
            removeLine(']: #', true),
            removeLine(''),
            removeLine('Original content'),
            removeLine(''),
            removeLine('[/edit:e1]: #', true),
            // Added line (at new line 8):
            addLine('REPLACED TEXT'),
          ],
        }],
      }],
    }

    const overlay = buildNodeTransactionOverlay(tx, 'test/node')
    expect(overlay).not.toBeNull()
    // Verify the overlay correctly identifies line 8 as added, not line 5
    expect(overlay!.addedLines.has(8)).toBe(true)
    expect(overlay!.addedLines.has(5)).toBe(false)

    const result = preprocessAnnotations(markdown, 'test', overlay)
    
    // "REPLACED TEXT" should be marked as added (it's at line 8 in the markdown)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('REPLACED TEXT')
    
    // Find the content inside the transaction-added div
    const addedMatch = result.match(/<div class="transaction-added">\s*([\s\S]*?)\s*<\/div>/)
    expect(addedMatch).not.toBeNull()
    expect(addedMatch![1]).toContain('REPLACED TEXT')
    expect(addedMatch![1]).not.toContain('Carlos sleeps peacefully')
  })

  it('renders removed content even when there are no added lines', () => {
    const markdown = `Line 1
Line 2
Line 3`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set(),
      removedGroups: [{ beforeLine: 2, lines: ['Deleted content'] }],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('Deleted content')
    expect(result).toContain('transaction-removed')
  })

  it('marks added lines with transaction-added div', () => {
    const markdown = `Line 1
Line 2
Line 3`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('Line 2')
    // Line 1 and Line 3 should not be in added divs
    const parts = result.split('<div class="transaction-added">')
    expect(parts[0]).toContain('Line 1')
    expect(parts[0]).not.toContain('Line 2')
  })

  it('inserts removed blockquote before added line', () => {
    const markdown = `Line 1
New content
Line 3`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2]),
      removedGroups: [{ beforeLine: 2, lines: ['Old content'] }],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    // Removed should appear before added
    const removedIdx = result.indexOf('transaction-removed')
    const addedIdx = result.indexOf('transaction-added')
    expect(removedIdx).toBeLessThan(addedIdx)
    expect(result).toContain('Old content')
  })

  it('does not mark empty lines as added', () => {
    const markdown = `Line 1

Line 3`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    // Empty line at position 2 should not create an added div
    // Count the number of transaction-added divs - should be 0
    expect(result.split('<div class="transaction-added">').length).toBe(1)
  })

  it('correctly handles line numbers with front matter annotation', () => {
    const markdown = `[
    kb_pin: [npc.test]
]: #

Content at line 5
Added content at line 6
More content at line 7`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([6]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('Added content at line 6')
  })

  it('handles section annotations with body content', () => {
    const markdown = `[section:ch1]: #

Chapter 1 content line 3
Added line 4
More content line 5

[/section:ch1]: #`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([4]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('Added line 4')
  })
})
