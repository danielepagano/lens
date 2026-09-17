/**
 * Line-level diff pair renderer.
 *
 * Shared by the legacy ```kb``` fence modal (`KbDiffModal`) and the inline
 * pending-proposal diff in the KB viewer. Both sides are just two strings —
 * `base`/`current` against `proposed` — so nothing about git or file paths
 * is involved.
 */

export type DiffLine = { kind: 'equal' | 'insert' | 'delete'; text: string }

export function computeLineDiff(current: string, proposed: string): DiffLine[] {
  const a = current.split('\n')
  const b = proposed.split('\n')
  const m = a.length
  const n = b.length

  // Build LCS table
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i] === b[j]) {
        dp[i][j] = 1 + dp[i + 1][j + 1]
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1])
      }
    }
  }

  // Reconstruct
  const result: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < m || j < n) {
    if (i < m && j < n && a[i] === b[j]) {
      result.push({ kind: 'equal', text: a[i] })
      i++
      j++
    } else if (j < n && (i >= m || dp[i][j + 1] >= dp[i + 1][j])) {
      result.push({ kind: 'insert', text: b[j] })
      j++
    } else {
      result.push({ kind: 'delete', text: a[i] })
      i++
    }
  }
  return result
}
