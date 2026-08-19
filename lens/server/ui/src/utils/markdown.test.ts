import { describe, it, expect } from 'vitest'
import {
  buildAnnotationBlocks,
  buildAnnotationLineSet,
  buildAnnotationDividerLabelHtml,
  buildAttachLinePickStates,
  buildNodeTransactionOverlay,
  collectAttachForbiddenLines,
  computeValidEndLines,
  computeValidStartLines,
  createMarkdownRenderer,
  prefixMountUrlsInRenderedHtml,
  parseChatDividerParams,
  preprocessAnnotations,
  preprocessBlockquotePills,
  preprocessKbMarkdownLinks,
  preprocessThinkingTags,
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

describe('preprocessThinkingTags', () => {
  it('collapses think blocks into a Thinking details section', () => {
    const markdown = `Before
<think>
line one
line two
</think>
After`
    const result = preprocessThinkingTags(markdown)
    expect(result).toContain('md-fence-thinking')
    expect(result).toContain('<span class="md-fence-tool-call-preview">Thinking</span>')
    expect(result).not.toContain('<think>')
    expect(result).toContain('line one')
  })

  it('renders thinking block body as markdown (not code)', () => {
    const md = createMarkdownRenderer()
    const markdown = `<thinking>
1. first
2. second
</thinking>`
    const rendered = md.render(preprocessThinkingTags(markdown))
    expect(rendered).toContain('md-fence-thinking')
    expect(rendered).toContain('<ol>')
    expect(rendered).toContain('<li>first</li>')
    expect(rendered).not.toContain('<thinking>')
  })
})

describe('preprocessKbMarkdownLinks', () => {
  it('replaces [text](kb/type.key) with a KB reference link', () => {
    const input = 'See [Frida](kb/character.frida) for details.'
    const result = preprocessKbMarkdownLinks(input)
    expect(result).toContain('data-kb-open-id="character.frida"')
    expect(result).toContain('Frida')
    expect(result).not.toContain('[Frida](kb/character.frida)')
  })

  it('preserves ordinary markdown links', () => {
    const input = 'Visit [example](https://example.com) and [local](/page).'
    const result = preprocessKbMarkdownLinks(input)
    expect(result).toBe(input)
  })

  it('skips links inside fenced code blocks', () => {
    const input = '```\n[secret](kb/npc.hidden)\n```'
    const result = preprocessKbMarkdownLinks(input)
    expect(result).toBe(input)
  })

  it('handles multiple kb links on the same line', () => {
    const input = '[Amy](kb/npc.amy) and [Bob](kb/npc.bob) are here.'
    const result = preprocessKbMarkdownLinks(input)
    expect(result).toContain('data-kb-open-id="npc.amy"')
    expect(result).toContain('data-kb-open-id="npc.bob"')
    expect(result).toContain('Amy')
    expect(result).toContain('Bob')
  })

  it('escapes HTML in link text and KB id', () => {
    const input = '[<script>](kb/npc.xss)'
    const result = preprocessKbMarkdownLinks(input)
    expect(result).not.toContain('<script>')
    expect(result).toContain('&lt;script&gt;')
  })

  it('renders via markdown-it as a link element', () => {
    const md = createMarkdownRenderer()
    const input = '[Frida](kb/character.frida)'
    const processed = preprocessKbMarkdownLinks(input)
    const html = md.render(processed)
    expect(html).toContain('data-kb-open-id="character.frida"')
    expect(html).toContain('Frida')
    // markdown-it with html:true passes through the anchor
    expect(html).toContain('<a ')
  })

  it('consumes [@type.key](kb/type.key) before @-pattern processing', () => {
    // This pattern would be broken by preprocessKbReferencePills if not
    // consumed first by preprocessKbMarkdownLinks.
    const input = '[@character.frida](kb/character.frida)'
    const processed = preprocessKbMarkdownLinks(input)
    // The @ should be inside the link text, not a standalone KB ref
    expect(processed).toContain('>@character.frida<')
    expect(processed).toContain('data-kb-open-id="character.frida"')
  })

  it('skips links in fenced code blocks with tilde fences', () => {
    const input = '~~~\n[secret](kb/npc.hidden)\n~~~'
    const result = preprocessKbMarkdownLinks(input)
    expect(result).toBe(input)
  })
})

describe('preprocessBlockquotePills', () => {
  it('turns > [label] rest into a quote-pill span', () => {
    const input = '> [position] On the road mid-line'
    const result = preprocessBlockquotePills(input)
    expect(result).toContain('<span class="quote-pill"')
    expect(result).toContain('>position<')
    expect(result).toContain('On the road mid-line')
  })

  it('skips blockquote-pill lines inside fenced code blocks', () => {
    const input = '```\n> [position] On the road mid-line\n```'
    const result = preprocessBlockquotePills(input)
    expect(result).toBe(input)
  })

  it('skips blockquote-pill lines inside tilde-fenced code blocks', () => {
    const input = '~~~\n> [position] On the road mid-line\n~~~'
    const result = preprocessBlockquotePills(input)
    expect(result).toBe(input)
  })

  it('still transforms pill lines outside the fence', () => {
    const input = '> [position] before\n```\n> [inside] fenced\n```\n> [conditions] after'
    const result = preprocessBlockquotePills(input)
    expect(result).toContain('>position<')
    expect(result).toContain('>conditions<')
    expect(result).toContain('> [inside] fenced')
    expect(result).not.toContain('>inside<')
  })
})

describe('createMarkdownRenderer', () => {
  it('adds target blank to all links when openLinksInNewTab is set', () => {
    const md = createMarkdownRenderer({ openLinksInNewTab: true })
    const html = md.render('[Example](https://example.com)')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('does not add target blank to ordinary links by default', () => {
    const md = createMarkdownRenderer()
    const html = md.render('[Example](https://example.com)')
    expect(html).not.toContain('target="_blank"')
  })
})

describe('prefixMountUrlsInRenderedHtml', () => {
  it('leaves HTML unchanged when project slug is null', () => {
    const html = '<img alt="x" src="/mount/file/foo.png">'
    expect(prefixMountUrlsInRenderedHtml(html, null)).toBe(html)
  })

  it('prefixes mount file and preview URLs in attributes', () => {
    const html =
      '<a href="/mount/file/a">x</a><img src="/mount/preview/b" alt="p">'
    expect(prefixMountUrlsInRenderedHtml(html, 'my-proj')).toBe(
      '<a href="/my-proj/mount/file/a">x</a><img src="/my-proj/mount/preview/b" alt="p">',
    )
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
    expect(result).toContain('annotation-heading')
    expect(result).toContain('href="#test/ch1"')
    expect(result).toContain('<div class="transaction-added">')
    expect(result).toContain('Added line 4')
  })

  it('prepends linked heading with type pill and hides duplicate ### for canonical summaries', () => {
    const markdown = `[section:play-scene-one]: #
<!-- section:play-scene-one -->

### Amy's Dream

> She wakes alone.

[/section:play-scene-one]: #`
    const result = preprocessAnnotations(markdown, 'campaign', null)
    expect(result).toContain('annotation-heading')
    expect(result).toContain('href="#campaign/play-scene-one"')
    expect(result).toContain("Amy's Dream")
    expect(result).toContain('pin-pill-inline')
    expect(result).toContain('play')
    expect(result).toContain('<!-- section:play-scene-one -->')
    expect(result).toContain('> She wakes alone.')
    expect(result).not.toMatch(/\n### Amy's Dream\n/)
  })

  it('does not duplicate ### when canonical summary title line is transaction-added', () => {
    const markdown = `[section:undressing]: #

<!-- section:undressing -->

### A Doll's Surrender

> Cecily speaks.

[/section:undressing]: #`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([5]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'Act-1/Walstein/a-dolls-company', overlay)
    const h3Matches = result.match(/<h3\b/g) ?? []
    expect(h3Matches).toHaveLength(1)
    expect(result).toContain('annotation-heading')
    expect(result).toContain('href="#Act-1/Walstein/a-dolls-company/undressing"')
    expect(result).toContain("A Doll's Surrender")
    expect(result).not.toMatch(/\n### A Doll's Surrender\n/)
  })

  it('wraps added fenced code blocks once inside annotation bodies', () => {
    const markdown = `[design:d1]: #

\`\`\`kb
---
id: encounter.kurmat-meeting
---
\`\`\`

[/design:d1]: #`
    const diff = makeDiff('test/node', [{
      oldStart: 1, newStart: 1,
      lines: [
        ' [design:d1]: #',
        ' ',
        '+```kb',
        '+---',
        '+id: encounter.kurmat-meeting',
        '+---',
        '+```',
        ' ',
        ' [/design:d1]: #',
      ],
    }])

    const overlay = buildNodeTransactionOverlay(diff, 'test/node')
    expect(overlay).not.toBeNull()

    const result = preprocessAnnotations(markdown, 'test', overlay)
    const addedWrappers = result.match(/<div class="transaction-added">/g) ?? []
    expect(addedWrappers).toHaveLength(1)
    expect(result).toContain('```kb')
    expect(result).toContain('id: encounter.kurmat-meeting')
    expect(result).not.toContain('```kb\n<div class="transaction-added">')
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
        { beforeLine: 3, lines: ['First removed block.', '> [Frida] prompt', 'Narrative from first play.'] },
        { beforeLine: 5, lines: ['Second removed block.', '> [GM] response', 'Narrative from second play.'] },
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

  it('strips HTML comments in transaction-removed so markdown never sees them', () => {
    const markdown = `A
B
C`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set(),
      removedGroups: [
        {
          beforeLine: 2,
          lines: ['<!-- ai:secret:', 'rot13 line', '-->', '', 'After comment prose.'],
        },
      ],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).not.toMatch(/<!--/)
    expect(result).not.toMatch(/-->/)
    expect(result).not.toContain('rot13 line')
    expect(result).toContain('After comment prose.')
  })

  it('strips multi-line HTML comments inside transaction-added (join lines before strip)', () => {
    const markdown = `Header
<!-- open
middle
-->
Kept line.`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2, 3, 4, 5]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('Kept line.')
    expect(result).toContain('<div class="transaction-added">')
    expect(result).not.toMatch(/<!--/)
    expect(result).not.toMatch(/-->/)
    expect(result).not.toContain('middle')
  })

  it('strips HTML comments closed with unicode dashes (hyphen + en dash before >)', () => {
    const en = '\u2013'
    const markdown = `X
<!-- hush
done-${en}>`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2, 3]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('X')
    expect(result).not.toContain('hush')
    expect(result).not.toMatch(/<!--/)
    expect(result).not.toContain(`-${en}>`)
  })

  it('strips comments closed with only en dash before > (typographic corrupt close)', () => {
    const en = '\u2013'
    const markdown = `Z
<!-- remark
comment. ${en}>
After.`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([2, 3, 4, 5]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'test', overlay)
    expect(result).toContain('After.')
    expect(result).not.toContain('remark')
    expect(result).not.toMatch(/<!--/)
    expect(result).not.toContain(`comment. ${en}>`)
  })

  it('drops canonical section marker lines from transaction-added (keeps blockquote highlight)', () => {
    const markdown = `[section:ab]: #

<!-- section:ab -->

### Winter Lights
> Snow falls softly.

[/section:ab]: #`
    const overlay: NodeTransactionOverlay = {
      addedLines: new Set([3, 4, 5, 6]),
      removedGroups: [],
    }
    const result = preprocessAnnotations(markdown, 'root', overlay)
    expect(result).toContain('annotation-heading')
    expect(result).toContain('Winter Lights')
    expect(result).toContain('Snow falls softly.')
    expect(result).not.toMatch(/<div class="transaction-added">\s*<\/div>/)
    const addedBlocks = result.match(/<div class="transaction-added">/g) ?? []
    expect(addedBlocks).toHaveLength(1)
    expect(result).not.toContain('<div class="transaction-added">\n\n<!-- section:ab -->')
  })

  it('treats <!-- Section:slug --> as canonical summary marker (case-insensitive)', () => {
    const markdown = `[section:ab]: #
<!-- Section:ab -->

### Winter Title

> Snow.

[/section:ab]: #`
    const result = preprocessAnnotations(markdown, 'root', null)
    expect(result).toContain('Winter Title')
    expect(result).not.toMatch(/\n### Winter Title\n/)
  })
})

describe('buildAnnotationBlocks', () => {
  it('parses single-line annotations', () => {
    const content = `Line 1
[write]: #
Line 3`
    const blocks = buildAnnotationBlocks(content)
    expect(blocks).toHaveLength(1)
    expect(blocks[0].operator).toBe('write')
    expect(blocks[0].lineStart).toBe(2)
    expect(blocks[0].lineEnd).toBe(2)
    expect(blocks[0].isClosed).toBe(false)
  })

  it('pairs open and close annotations', () => {
    const content = `[section:ch1]: #
Some body
[/section:ch1]: #`
    const blocks = buildAnnotationBlocks(content)
    // The paired open+close block, plus the standalone close (consumed by pairing)
    const paired = blocks.filter(b => b.isClosed && !b.isSelfClosing && !b.isClosing)
    expect(paired).toHaveLength(1)
    expect(paired[0].lineStart).toBe(1)
    expect(paired[0].lineEnd).toBe(3)
    expect(paired[0].closeLineStart).toBe(3)
    expect(paired[0].closeLineEnd).toBe(3)
  })

  it('parses front matter blocks', () => {
    const content = `[
  kb_pin: [npc.test]
]: #
Content`
    const blocks = buildAnnotationBlocks(content)
    const fm = blocks.filter(b => b.isFrontMatter)
    expect(fm).toHaveLength(1)
    expect(fm[0].lineStart).toBe(1)
    expect(fm[0].lineEnd).toBe(3)
  })

  it('parses multi-line annotations', () => {
    const content = `[write
  prompt: continue
]: #
Body text`
    const blocks = buildAnnotationBlocks(content)
    const opens = blocks.filter(b => !b.isClosing && !b.isFrontMatter)
    expect(opens).toHaveLength(1)
    expect(opens[0].lineStart).toBe(1)
    expect(opens[0].lineEnd).toBe(3)
    expect(opens[0].operator).toBe('write')
  })

  it('parses self-closing annotations', () => {
    const content = `[section:ch1/]: #`
    const blocks = buildAnnotationBlocks(content)
    expect(blocks).toHaveLength(1)
    expect(blocks[0].isSelfClosing).toBe(true)
    expect(blocks[0].isClosed).toBe(true)
  })
})

describe('buildAnnotationLineSet (refactored)', () => {
  it('returns same results as before for basic content', () => {
    const content = `Line 1
[section:ch1]: #
Body
[/section:ch1]: #
Line 5`
    const set = buildAnnotationLineSet(content)
    expect(set.has(1)).toBe(false)
    expect(set.has(2)).toBe(true)
    expect(set.has(3)).toBe(false)
    expect(set.has(4)).toBe(true)
    expect(set.has(5)).toBe(false)
  })

  it('marks front matter lines', () => {
    const content = `[
  kb_pin: [npc.test]
]: #
Content`
    const set = buildAnnotationLineSet(content)
    expect(set.has(1)).toBe(true)
    expect(set.has(2)).toBe(true)
    expect(set.has(3)).toBe(true)
    expect(set.has(4)).toBe(false)
  })

  it('marks multi-line annotation lines', () => {
    const content = `[write
  prompt: go
]: #
Body`
    const set = buildAnnotationLineSet(content)
    expect(set.has(1)).toBe(true)
    expect(set.has(2)).toBe(true)
    expect(set.has(3)).toBe(true)
    expect(set.has(4)).toBe(false)
  })
})

describe('collectAttachForbiddenLines', () => {
  it('forbids all front matter lines including close', () => {
    const content = `[
  kb_pin: [npc.test]
]: #
Content`
    const f = collectAttachForbiddenLines(content)
    expect(f.has(1)).toBe(true)
    expect(f.has(2)).toBe(true)
    expect(f.has(3)).toBe(true)
    expect(f.has(4)).toBe(false)
  })

  it('forbids interior of multiline tag but not closing line', () => {
    const content = `[write
  prompt: go
]: #
Body`
    const f = collectAttachForbiddenLines(content)
    expect(f.has(1)).toBe(true)
    expect(f.has(2)).toBe(true)
    expect(f.has(3)).toBe(false)
    expect(f.has(4)).toBe(false)
  })

  it('buildAttachLinePickStates marks pickable body lines', () => {
    const content = `[write
  prompt: go
]: #
Body`
    const m = buildAttachLinePickStates(content)
    expect(m.get(3)).toBe('pickable')
    expect(m.get(4)).toBe('pickable')
    expect(m.get(1)).toBe('annotation')
  })
})

describe('computeValidEndLines — edit mode', () => {
  it('allows end lines before any annotation', () => {
    const content = `Line 1
Line 2
Line 3
[section:ch1]: #
Body
[/section:ch1]: #`
    const valid = computeValidEndLines(content, 1)
    expect(valid.has(1)).toBe(true)
    expect(valid.has(2)).toBe(true)
    expect(valid.has(3)).toBe(true)
  })

  it('rejects end lines that would include an annotation start', () => {
    const content = `Line 1
Line 2
[section:ch1]: #
Body
[/section:ch1]: #
Line 6`
    // Start at line 1: annotation starts at line 3, so ceiling is 2
    const valid = computeValidEndLines(content, 1)
    expect(valid.has(1)).toBe(true)
    expect(valid.has(2)).toBe(true)
    expect(valid.has(3)).toBe(false)  // annotation line
    expect(valid.has(4)).toBe(false)  // past ceiling
    expect(valid.has(5)).toBe(false)  // past ceiling
    expect(valid.has(6)).toBe(false)  // past ceiling
  })

  it('allows end lines when start is after annotations', () => {
    const content = `[section:ch1]: #
Body
[/section:ch1]: #
Line 4
Line 5`
    // Start at line 4 (after all annotations)
    const valid = computeValidEndLines(content, 4)
    expect(valid.has(4)).toBe(true)
    expect(valid.has(5)).toBe(true)
  })

  it('handles front matter as annotation block', () => {
    const content = `[
  kb_pin: [npc.test]
]: #
Line 4
Line 5`
    // Start at line 4: front matter block starts at line 1 which is <= 4, not > 4
    // So ceiling is 5 (no annotation starts after line 4)
    const valid = computeValidEndLines(content, 4)
    expect(valid.has(4)).toBe(true)
    expect(valid.has(5)).toBe(true)
  })
})

describe('computeValidStartLines — edit mode', () => {
  it('allows any non-annotation line', () => {
    const content = `Line 1
[section:ch1]: #
Body
[/section:ch1]: #
Line 5`
    const valid = computeValidStartLines(content)
    expect(valid.has(1)).toBe(true)
    expect(valid.has(2)).toBe(false)  // annotation
    expect(valid.has(3)).toBe(true)
    expect(valid.has(4)).toBe(false)  // annotation
    expect(valid.has(5)).toBe(true)
  })
})

describe('annotation divider pills (chat)', () => {
  it('parses chat params with kb_pin list (ignores kb_pin lines)', () => {
    const block = `    as_kb_id: person.amy
    kb_pin:
    - person.carlos
    prompt: cute morning banter
    with_kb_id: person.carlos`
    const p = parseChatDividerParams(block)
    expect(p.asKbId).toBe('person.amy')
    expect(p.withKbId).toBe('person.carlos')
  })

  it('buildAnnotationDividerLabelHtml keeps toLabel before chat pill', () => {
    const param = `    as_kb_id: person.amy
    with_kb_id: person.carlos`
    const html = buildAnnotationDividerLabelHtml('chat', 'chat-amy-carlos-cute-morning-banter', param)
    expect(html).toContain('annotation-divider-title')
    expect(html).toContain('Amy Carlos Cute Morning Banter')
    expect(html).toContain('chat:amy-carlos')
    expect(html).toContain('pin-pill-annotation-divider')
    expect(html.indexOf('annotation-divider-title')).toBeLessThan(html.indexOf('chat:amy-carlos'))
    expect(html).not.toContain('pin-pill-inline')
    expect(html).not.toContain('pin-pill-unpin')
  })

  it('preprocessAnnotations emits title then chat divider pills from multiline params', () => {
    const markdown = `[chat:chat-amy-carlos-cute-morning-banter
    as_kb_id: person.amy
    with_kb_id: person.carlos
]: #

`
    const result = preprocessAnnotations(markdown, 'story', null)
    expect(result).toContain('annotation-divider')
    expect(result).toContain('Amy Carlos Cute Morning Banter')
    expect(result).toContain('chat:amy-carlos')
    expect(result).not.toContain('pin-pill-inline')
    expect(result).not.toContain('pin-pill-unpin')
  })
})
