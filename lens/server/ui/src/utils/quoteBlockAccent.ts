import { tick } from 'svelte'

/** Copy `--quote-pill-accent` from the first `.quote-pill` in each blockquote onto the blockquote for skin styling. */
export function applyQuoteBlockAccents(root: HTMLElement): void {
  root.querySelectorAll('blockquote').forEach((bq) => {
    bq.classList.remove('has-quote-accent')
    ;(bq as HTMLElement).style.removeProperty('--quote-bq-accent')
  })
  root.querySelectorAll('.quote-pill').forEach((pill) => {
    const bq = pill.closest('blockquote')
    if (!bq || bq.classList.contains('has-quote-accent')) return
    const accent = (pill as HTMLElement).style.getPropertyValue('--quote-pill-accent').trim()
    if (!accent) return
    bq.classList.add('has-quote-accent')
    ;(bq as HTMLElement).style.setProperty('--quote-bq-accent', accent)
  })
}

export function syncQuoteBlockAccents(
  node: HTMLElement,
  _renderedKey: string,
): { update(): void } {
  const schedule = () => {
    void tick().then(() => applyQuoteBlockAccents(node))
  }
  schedule()
  return { update: schedule }
}
