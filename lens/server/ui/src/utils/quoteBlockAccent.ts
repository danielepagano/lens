import { tick } from 'svelte'

/** Copy `--quote-pill-accent` from the first `.quote-pill` in each blockquote onto the blockquote for skin styling. */
export function applyQuoteBlockAccents(root: HTMLElement, pcKeys: Set<string>): void {
  root.querySelectorAll('blockquote').forEach((bq) => {
    bq.classList.remove('has-quote-accent', 'is-pc-quote')
    ;(bq as HTMLElement).style.removeProperty('--quote-bq-accent')
  })
  root.querySelectorAll('.quote-pill').forEach((pill) => {
    const bq = pill.closest('blockquote')
    if (!bq || bq.classList.contains('has-quote-accent')) return
    const accent = (pill as HTMLElement).style.getPropertyValue('--quote-pill-accent').trim()
    if (!accent) return
    bq.classList.add('has-quote-accent')
    ;(bq as HTMLElement).style.setProperty('--quote-bq-accent', accent)
    const label = (pill.textContent ?? '').trim().toLowerCase()
    if (label && pcKeys.has(label)) {
      bq.classList.add('is-pc-quote')
    }
  })
}

interface SyncParams {
  key: string
  pcKeys: Set<string>
}

export function syncQuoteBlockAccents(
  node: HTMLElement,
  params: SyncParams,
): { update(params: SyncParams): void } {
  let current = params
  const schedule = () => {
    void tick().then(() => applyQuoteBlockAccents(node, current.pcKeys))
  }
  schedule()
  return {
    update(p: SyncParams) {
      current = p
      schedule()
    },
  }
}
