export function subscribeCoarsePointer(onChange: (coarse: boolean) => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => {}
  }
  const mql = window.matchMedia('(pointer: coarse)')
  onChange(mql.matches)
  const handler = () => onChange(mql.matches)
  mql.addEventListener('change', handler)
  return () => mql.removeEventListener('change', handler)
}

export function isCoarsePointer(): boolean {
  return (
    typeof globalThis !== 'undefined' &&
    typeof globalThis.matchMedia === 'function' &&
    globalThis.matchMedia('(pointer: coarse)').matches
  )
}
