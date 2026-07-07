export type SemverTriple = [major: number, minor: number, patch: number]

const SEMVER_REGEX = /^v?(\d+)\.(\d+)\.(\d+)$/

export function parseSemverTriple(value: string | null | undefined): SemverTriple | null {
  if (!value) return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const match = trimmed.match(SEMVER_REGEX)
  if (!match) return null
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

export function compareSemverTriples(a: SemverTriple, b: SemverTriple): number {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] === b[i]) continue
    return a[i] > b[i] ? 1 : -1
  }
  return 0
}

export function formatVersionLabel(value: string | null | undefined): string {
  if (!value) return '—'
  const trimmed = value.trim()
  if (!trimmed) return '—'
  return `v${trimmed.replace(/^v/, '')}`
}

export function shouldShowPendingReleaseRequest(
  requestedVersion: string | null | undefined,
  installedVersion: string | null | undefined
): boolean {
  if (!requestedVersion) return false
  const requestedSemver = parseSemverTriple(requestedVersion)
  const installedSemver = parseSemverTriple(installedVersion)
  if (installedVersion && requestedSemver && installedSemver) {
    return compareSemverTriples(requestedSemver, installedSemver) > 0
  }
  if (!installedVersion) return true
  return requestedVersion.trim() !== installedVersion.trim()
}
