import type { TreeNode } from '../../services/api'

/** Convert display-format address (e.g. `/`, `/chapter-1`) to API-format (`story`, `story/chapter-1`). */
export function displayAddrToNavAddr(
  displayAddr: string,
  nodeTreeCache: TreeNode[] | null,
): string | null {
  if (!nodeTreeCache || nodeTreeCache.length === 0) return null
  const root = nodeTreeCache[0]!
  const normalized = displayAddr.replace(/\/+$/g, '')
  if (normalized === '' || normalized === '/') return root.address
  if (normalized.startsWith('/')) return root.address + normalized
  return normalized
}

export function navAddrToDisplayAddr(
  navAddr: string,
  nodeTreeCache: TreeNode[] | null,
): string | null {
  if (!nodeTreeCache || nodeTreeCache.length === 0) return null
  const root = nodeTreeCache[0]!
  if (navAddr === root.address) return '/'
  if (navAddr.startsWith(root.address + '/')) return navAddr.slice(root.address.length)
  return null
}
