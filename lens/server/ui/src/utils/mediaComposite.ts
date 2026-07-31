import type { MountMetadata } from '../services/api'

export type CompositeRole = 'foreground' | 'background'

/** Mirrors `lens.core.media.metadata.MediaMetadata.composite_role`. */
export function compositeRole(meta: MountMetadata): CompositeRole | null {
  const value = meta.composite
  if (typeof value !== 'string') return null
  const trimmed = value.trim().toLowerCase()
  return trimmed === 'foreground' || trimmed === 'background' ? trimmed : null
}

export function otherCompositeRole(role: CompositeRole): CompositeRole {
  return role === 'foreground' ? 'background' : 'foreground'
}
