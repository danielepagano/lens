import { describe, it, expect } from 'vitest'
import {
  buildNodeTransactionOverlay,
  preprocessAnnotations,
  type NodeTransactionOverlay,
} from './markdown'

/**
 * Build a raw unified diff string for a single file.
 * `address` is like 'test/node', hunks is an array of { oldStart, newStart, lines }
 * where each line is prefixed with '+', '-', or ' '.
 */
function makeDiff(
  address: string,
  hunks: { oldStart: number; newStart: number; lines: string[] }[],
): string {
  const path = `narrative/${address}/_node.md`
  const parts = [
    `diff --git a/${path} b/${path}`,
    `--- a/${path}`,
    `+++ b/${path}`,
  ]
  for (const h of hunks) {
    parts.push(`@@ -${h.oldStart},99 +${h.newStart},99 @@`)
    parts.push(...h.lines)
  }
  return parts.join('\n') + '\n'
}

describe('buildNodeTransactionOverlay', () => {
  it('returns null when no diff provided', () => {
    expect(buildNodeTransactionOverlay(null, 'some/address')).toBeNull()
    expect(buildNodeTransactionOverlay('', 'some/address')).toBeNull()
  })

  it('returns null when address does not match any file', () => {
    const diff = makeDiff('other/address', [])
    expect(buildNodeTransactionOverlay(diff, 'some/address')).toBeNull()
  })

  it('returns null when there are no changes (empty hunks)', () => {
    const diff = makeDiff('test/node', [])
    expect(buildNodeTransactionOverlay(diff, 'test/node')).toBeNull()
  })

  it('tracks added line numbers correctly', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: ['+first added line', '+second added line'],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.addedLines).toEqual(new Set([1, 2]))
  })

  it('includes annotation added lines (stripped later by preprocessAnnotations)', () => {
    // Unlike the old code, we no longer filter added annotation lines here —
    // they are naturally stripped by preprocessAnnotations.
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: ['+[write]: #', '+actual content', '+[/write]: #'],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    // All 3 lines are tracked as added (annotations will be stripped during rendering)
    expect(result!.addedLines).toEqual(new Set([1, 2, 3]))
  })

  it('tracks removed groups with correct beforeLine', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 5, newStart: 5,
      lines: ['-old content', '+new content'],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0]).toEqual({
      beforeLine: 5,
      lines: ['old content'],
    })
  })

  it('groups consecutive removed lines together', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 5, newStart: 5,
      lines: ['-line one', '-line two', '-line three', '+replacement'],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0].lines).toEqual(['line one', 'line two', 'line three'])
  })

  it('filters annotation lines from removed groups', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 5, newStart: 5,
      lines: [
        '-[edit:e1_2]: #',
        '-',
        '-actual removed content',
        '-',
        '-[/edit:e1_2]: #',
        '+REPLACEMENT',
      ],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0].lines).toEqual([
      '',
      'actual removed content',
      '',
    ])
  })

  it('filters multi-line annotation blocks from removed groups', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 8, newStart: 5,
      lines: [
        '-[edit:e8_9',
        '-  manual: true',
        '-  prompt: new text',
        '-]: #',
        '-',
        '-original paragraph',
        '-',
        '-[/edit:e8_9]: #',
        '+new text',
      ],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.addedLines).toEqual(new Set([5]))
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0].lines).toEqual([
      '',
      'original paragraph',
      '',
    ])
  })

  it('handles trailing removed lines (no add after removes)', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 5, newStart: 5,
      lines: ['-deleted line one', '-deleted line two'],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.addedLines.size).toBe(0)
    expect(result!.removedGroups).toHaveLength(1)
    expect(result!.removedGroups[0]).toEqual({
      beforeLine: 5,
      lines: ['deleted line one', 'deleted line two'],
    })
  })

  it('handles context lines for accurate line tracking', () => {
    const diff = makeDiff('test/node', [{
      oldStart: 5, newStart: 5,
      lines: [
        ' Carlos sleeps peacefully',
        '   ',
        ' [/section:s1]: #',
        '-Original content',
        '+REPLACED TEXT',
      ],
    }])
    const result = buildNodeTransactionOverlay(diff, 'test/node')
    expect(result).not.toBeNull()
    expect(result!.addedLines.has(8)).toBe(true)
    expect(result!.addedLines.has(5)).toBe(false)
  })
})

describe('preprocessAnnotations with overlay', () => {
  it('correctly identifies added line when context lines precede changes', () => {
    const markdown = `Line 1
Line 2
[section:s1]: #

Carlos sleeps peacefully

[/section:s1]: #
REPLACED TEXT

[write]: #

More content`

    const diff = makeDiff('test/node', [{
      oldStart: 5, newStart: 5,
      lines: [
        ' Carlos sleeps peacefully',
        '   ',
        ' [/section:s1]: #',
        '-[edit:e1]: #',
        '-Original content',
        '-[/edit:e1]: #',
        '+REPLACED TEXT',
      ],
    }])

    const overlay = buildNodeTransactionOverlay(diff, 'test/node')
    expect(overlay).not.toBeNull()
    expect(overlay!.addedLines.has(8)).toBe(true)

    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('REPLACED TEXT')

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
    const parts = result.split('<div class="transaction-added">')
    expect(parts[0]).toContain('Line 1')
    expect(parts[0]).not.toContain('Line 2')
  })

  it('inserts removed block before added line', () => {
    const markdown = `Line 1
New content
Line 3`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2]),
      removedGroups: [{ beforeLine: 2, lines: ['Old content'] }],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
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

  it('does not render diff markers on operator annotation changes', () => {
    // When an operator multi-line annotation changes, lines inside it are
    // consumed by preprocessAnnotations and diff markers should not appear.
    const markdown = `[write
    prompt: continue the story
]: #

Some narrative content.`

    // Diff includes a changed param line inside the annotation block
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2]),
      removedGroups: [{ beforeLine: 2, lines: ['    prompt: old prompt'] }],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    // The multi-line annotation block is consumed, so no diff artifacts
    expect(result).not.toContain('transaction-added')
    expect(result).not.toContain('transaction-removed')
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

  it('shows all removed groups for a section when replacement spans opening to closing line', () => {
    // Section replaces multiple blocks (e.g. two play blocks). Removed content is keyed
    // to opening line and to a line before the closing; both must appear.
    const markdown = `Preamble one
Preamble two
[section:fortress-arrival]: #

New body line

[/section:fortress-arrival]: #`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([5]),
      removedGroups: [
        { beforeLine: 3, lines: ['First removed block.', '> [FRIDA] prompt', 'Narrative from first play.'] },
        { beforeLine: 5, lines: ['Second removed block.', '> [DM] response', 'Narrative from second play.'] },
      ],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-removed">')
    expect(result).toContain('First removed block.')
    expect(result).toContain('Narrative from first play.')
    expect(result).toContain('Second removed block.')
    expect(result).toContain('Narrative from second play.')
    const removedBlocks = result.match(/<div class="transaction-removed">/g)
    expect(removedBlocks).toHaveLength(2)
  })

  it('does not render diff markers when front-matter pins are added', () => {
    // Real-world: user adds a kb_pin via the pin command.
    // The file goes from no front-matter to having a front-matter block.
    // The diff marks all front-matter lines as added, but they should be invisible.
    const markdown = `[
    kb_pin:
    - part.head
]: #

It's morning in Amy's apartment.`

    // All front-matter lines are added (lines 1-4)
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: [
        '+[',
        '+    kb_pin:',
        '+    - part.head',
        '+]: #',
        '+',
        ' It\'s morning in Amy\'s apartment.',
      ],
    }])

    const overlay = buildNodeTransactionOverlay(diff, 'test/node')
    expect(overlay).not.toBeNull()

    const result = preprocessAnnotations(markdown, 'test', overlay)
    // Front-matter block is consumed — no diff markers should appear for it
    expect(result).not.toContain('transaction-added')
    expect(result).not.toContain('transaction-removed')
    expect(result).not.toContain('[')
    expect(result).not.toContain('kb_pin')
    expect(result).toContain("It's morning in Amy's apartment.")
  })

  it('does not render diff markers when front-matter pins change', () => {
    // Real-world: user modifies an existing pin list.
    const markdown = `[
    kb_pin:
    - npc.amy
    - npc.bob
]: #

Some narrative content.`

    // Diff shows one pin line changed
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: [
        ' [',
        '     kb_pin:',
        '     - npc.amy',
        '-    - npc.alice',
        '+    - npc.bob',
        ' ]: #',
      ],
    }])

    const overlay = buildNodeTransactionOverlay(diff, 'test/node')
    // Removed line is inside a front-matter block — should be filtered
    if (overlay) {
      const result = preprocessAnnotations(markdown, 'test', overlay)
      expect(result).not.toContain('transaction-added')
      expect(result).not.toContain('transaction-removed')
    }
  })

  it('marks write operator output as added (end-to-end)', () => {
    // Real-world: write operator appends content at the end of a node.
    // File was "Existing content.\n[write]: #\n" (committed),
    // now is "Existing content.\nNew paragraph from LLM.\n[write]: #\n"
    const markdown = `Existing content.
New paragraph from LLM.
[write]: #
`
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: [
        ' Existing content.',
        '+New paragraph from LLM.',
        ' [write]: #',
      ],
    }])

    const overlay = buildNodeTransactionOverlay(diff, 'test/node')
    expect(overlay).not.toBeNull()
    expect(overlay!.addedLines.has(2)).toBe(true)

    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('New paragraph from LLM.')
    // The [write]: # annotation should be stripped (no id = cursor marker)
    expect(result).not.toContain('[write]: #')
  })

  it('marks edit operator replacement as added with removed shown (end-to-end)', () => {
    // Real-world: edit operator replaces line 2. Claim tags are in staged,
    // replacement is in unstaged. The pending diff shows claim tags removed
    // and replacement added.
    const markdown = `Line one.
Replacement line two.
`
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: [
        ' Line one.',
        '-[edit:e2_2',
        '-    manual: true',
        '-    prompt: Replacement line two.',
        '-]: #',
        '-Line two.',
        '-',
        '-[/edit:e2_2]: #',
        '+Replacement line two.',
      ],
    }])

    const overlay = buildNodeTransactionOverlay(diff, 'test/node')
    expect(overlay).not.toBeNull()
    expect(overlay!.addedLines.has(2)).toBe(true)
    // Removed group should contain only "Line two." and "" (annotations filtered)
    expect(overlay!.removedGroups).toHaveLength(1)
    expect(overlay!.removedGroups[0].lines).toEqual(['Line two.', ''])

    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('Replacement line two.')
    expect(result).toContain('<div class="transaction-removed">')
    expect(result).toContain('Line two.')
    // Removed should appear before added
    const removedIdx = result.indexOf('transaction-removed')
    const addedIdx = result.indexOf('transaction-added')
    expect(removedIdx).toBeLessThan(addedIdx)
  })
})
