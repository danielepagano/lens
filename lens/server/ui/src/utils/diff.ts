/**
 * Minimal unified diff parser for transaction overlay rendering.
 *
 * Parses raw `git diff` output into structured hunks, and maps
 * `narrative/` file paths to node addresses.
 */

export interface ParsedDiffLine {
  kind: 'add' | 'remove' | 'context'
  text: string
}

export interface ParsedHunk {
  oldStart: number
  newStart: number
  lines: ParsedDiffLine[]
}

export interface ParsedFileDiff {
  path: string
  hunks: ParsedHunk[]
}

const FILE_RE = /^\+\+\+ b\/(.+)$/
const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/**
 * Convert a narrative file path to a node address.
 * `narrative/foo/bar/_node.md` → `foo/bar`
 * `narrative/foo/bar/leaf.md` → `foo/bar/leaf`
 * Non-narrative paths return null.
 */
export function pathToAddress(path: string): string | null {
  if (!path.startsWith('narrative/')) return null
  // Strip 'narrative/' prefix
  let rest = path.slice('narrative/'.length)
  // Strip leading narrative name (first segment)
  const slashIdx = rest.indexOf('/')
  if (slashIdx < 0) return null
  const narrativeName = rest.slice(0, slashIdx)
  rest = rest.slice(slashIdx + 1)
  // Strip _node.md or .md suffix
  if (rest === '_node.md') {
    // Root node of the narrative tree
    return narrativeName
  } else if (rest.endsWith('/_node.md')) {
    rest = rest.slice(0, -'/_node.md'.length)
  } else if (rest.endsWith('.md')) {
    rest = rest.slice(0, -'.md'.length)
  }
  return narrativeName + '/' + rest
}

/** Parse raw unified diff text into structured file diffs. */
export function parseDiff(text: string): ParsedFileDiff[] {
  if (!text.trim()) return []

  const files: ParsedFileDiff[] = []
  let currentFile: ParsedFileDiff | null = null
  let currentHunk: ParsedHunk | null = null

  for (const raw of text.split('\n')) {
    const fm = FILE_RE.exec(raw)
    if (fm) {
      currentFile = { path: fm[1], hunks: [] }
      files.push(currentFile)
      currentHunk = null
      continue
    }

    if (
      raw.startsWith('--- ') ||
      raw.startsWith('diff ') ||
      raw.startsWith('index ') ||
      raw.startsWith('new file') ||
      raw.startsWith('deleted file') ||
      raw.startsWith('old mode') ||
      raw.startsWith('new mode')
    ) continue

    if (!currentFile) continue

    const hm = HUNK_RE.exec(raw)
    if (hm) {
      currentHunk = { oldStart: parseInt(hm[1]), newStart: parseInt(hm[2]), lines: [] }
      currentFile.hunks.push(currentHunk)
      continue
    }

    if (!currentHunk) continue
    if (raw.startsWith('\\')) continue // "\ No newline at end of file"

    if (raw.startsWith('+') && !raw.startsWith('+++')) {
      currentHunk.lines.push({ kind: 'add', text: raw.slice(1) })
    } else if (raw.startsWith('-') && !raw.startsWith('---')) {
      currentHunk.lines.push({ kind: 'remove', text: raw.slice(1) })
    } else if (raw.startsWith(' ')) {
      currentHunk.lines.push({ kind: 'context', text: raw.slice(1) })
    }
  }

  return files
}

/** Find the parsed hunks for the file matching the given node address. */
export function findFileHunks(rawDiff: string, address: string): ParsedHunk[] | null {
  const files = parseDiff(rawDiff)
  for (const f of files) {
    if (pathToAddress(f.path) === address) {
      return f.hunks
    }
  }
  return null
}
