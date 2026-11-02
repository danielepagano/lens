import type { TriggerRehearsal } from '../services/api'

/**
 * The same report `lens test-play --trigger` prints (`lens/cli/operators/test_play.py`).
 */
export function formatRehearsal(r: TriggerRehearsal, verbose: boolean): string {
  const pinned = r.targets.length ? ` with ${r.targets.map((t) => `${t}+`).join(', ')}` : ''
  const lines = [`at ${r.node}${pinned} — player: ${r.player_line}`]
  if (r.at) lines.push(`scene: ${r.at}`)
  r.runs.forEach((run, i) => {
    let verdict: string
    if (run.outcome === 'interrupted') verdict = 'interrupted'
    else if (run.outcome === 'suggested') verdict = `suggested ${r.slug}  ✓`
    else if (run.outcome === 'stopped-short') verdict = `stopped short; suggested ${r.slug} on the next beat  ✓`
    else if (run.markers.length || run.then_markers.length) verdict = 'wrong marker  ✗'
    else if (run.then_text !== null) verdict = 'no marker, nor on the next beat  ✗'
    else verdict = 'no marker  ✗'
    const extra = run.other_markers.length ? `  (also: ${run.other_markers.join(', ')})` : ''
    lines.push(`run ${i + 1}: ${verdict}${extra}`)
    if (verbose) {
      lines.push('', run.text)
      if (run.then_text !== null) lines.push('', `> [then] ${r.then}`, '', run.then_text)
      lines.push('')
    }
  })
  const after = r.then ? `, +${r.hits_after} after one more beat` : ''
  lines.push(`${r.hits}/${r.runs.length} suggested ${r.slug}${after}${verbose ? '' : ' — read the beats with --verbose'}`)
  return lines.join('\n')
}
