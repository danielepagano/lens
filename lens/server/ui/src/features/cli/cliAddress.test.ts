import { describe, it, expect } from 'vitest'
import type { TreeNode } from '../../services/api'
import { displayAddrToNavAddr, navAddrToDisplayAddr } from './cliAddress'

const TREE: TreeNode[] = [
  {
    address: 'story',
    key: 'story',
    children: [
      {
        address: 'story/chapter-1',
        key: 'chapter-1',
        children: [],
      },
    ],
  },
]

describe('cliAddress', () => {
  it('maps root display / to root nav address', () => {
    expect(displayAddrToNavAddr('/', TREE)).toBe('story')
    expect(displayAddrToNavAddr('', TREE)).toBe('story')
  })

  it('maps nested display path to nav address', () => {
    expect(displayAddrToNavAddr('/chapter-1', TREE)).toBe('story/chapter-1')
  })

  it('returns null when tree cache is empty', () => {
    expect(displayAddrToNavAddr('/', null)).toBeNull()
    expect(displayAddrToNavAddr('/', [])).toBeNull()
  })

  it('maps nav address back to display format', () => {
    expect(navAddrToDisplayAddr('story', TREE)).toBe('/')
    expect(navAddrToDisplayAddr('story/chapter-1', TREE)).toBe('/chapter-1')
  })

  it('returns null for unknown nav address', () => {
    expect(navAddrToDisplayAddr('other/node', TREE)).toBeNull()
  })
})
