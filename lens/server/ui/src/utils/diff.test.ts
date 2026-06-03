import { describe, it, expect } from 'vitest'
import { pathToAddress, parseDiff, findFileHunks } from './diff'

describe('pathToAddress', () => {
  it('converts _node.md paths', () => {
    expect(pathToAddress('narrative/story/chapter-1/_node.md')).toBe('story/chapter-1')
  })

  it('converts leaf .md paths', () => {
    expect(pathToAddress('narrative/story/chapter-1/scene.md')).toBe('story/chapter-1/scene')
  })

  it('returns null for non-narrative paths', () => {
    expect(pathToAddress('knowledge/npc/amy.md')).toBeNull()
  })

  it('converts root _node.md paths', () => {
    expect(pathToAddress('narrative/story/_node.md')).toBe('story')
  })

  it('returns null for bare narrative directory', () => {
    expect(pathToAddress('narrative/story')).toBeNull()
  })
})

const SAMPLE_DIFF = `diff --git a/narrative/story/chapter-1/_node.md b/narrative/story/chapter-1/_node.md
index abc1234..def5678 100644
--- a/narrative/story/chapter-1/_node.md
+++ b/narrative/story/chapter-1/_node.md
@@ -5,4 +5,4 @@ some context header
 Carlos sleeps peacefully

 [/section:s1]: #
-Original content
+REPLACED TEXT
`

describe('parseDiff', () => {
  it('parses a simple diff', () => {
    const files = parseDiff(SAMPLE_DIFF)
    expect(files).toHaveLength(1)
    expect(files[0].path).toBe('narrative/story/chapter-1/_node.md')
    expect(files[0].hunks).toHaveLength(1)

    const hunk = files[0].hunks[0]
    expect(hunk.oldStart).toBe(5)
    expect(hunk.newStart).toBe(5)
    // The blank line between context lines has no space prefix in the test
    // string, so the parser skips it (real git diffs use a single space).
    expect(hunk.lines).toHaveLength(4)
    expect(hunk.lines[0]).toEqual({ kind: 'context', text: 'Carlos sleeps peacefully' })
    expect(hunk.lines[2]).toEqual({ kind: 'remove', text: 'Original content' })
    expect(hunk.lines[3]).toEqual({ kind: 'add', text: 'REPLACED TEXT' })
  })

  it('returns empty array for empty input', () => {
    expect(parseDiff('')).toEqual([])
    expect(parseDiff('  \n  ')).toEqual([])
  })

  it('handles multiple files', () => {
    const diff = `diff --git a/narrative/story/a/_node.md b/narrative/story/a/_node.md
--- a/narrative/story/a/_node.md
+++ b/narrative/story/a/_node.md
@@ -1,2 +1,2 @@
-old
+new
diff --git a/narrative/story/b/_node.md b/narrative/story/b/_node.md
--- a/narrative/story/b/_node.md
+++ b/narrative/story/b/_node.md
@@ -1,2 +1,2 @@
-old2
+new2
`
    const files = parseDiff(diff)
    expect(files).toHaveLength(2)
    expect(files[0].path).toBe('narrative/story/a/_node.md')
    expect(files[1].path).toBe('narrative/story/b/_node.md')
  })
})

describe('findFileHunks', () => {
  it('finds hunks matching address', () => {
    const hunks = findFileHunks(SAMPLE_DIFF, 'story/chapter-1')
    expect(hunks).not.toBeNull()
    expect(hunks!).toHaveLength(1)
  })

  it('returns null for non-matching address', () => {
    expect(findFileHunks(SAMPLE_DIFF, 'story/chapter-2')).toBeNull()
  })

  it('returns null for empty diff', () => {
    expect(findFileHunks('', 'story/chapter-1')).toBeNull()
  })
})
