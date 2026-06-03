export const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
export const AUDIO_EXTS = new Set(['.mp3', '.wav'])
export const VIDEO_EXTS = new Set(['.mp4', '.webm', '.mov', '.avi'])
export const PLAIN_PRE_EXTS = new Set(['.txt', '.json', '.yaml', '.yml'])
export const TEXT_EXTS = new Set(['.txt', '.json', '.yaml', '.yml', '.md'])

export function mountPathExt(pathOrName: string): string {
  const dot = pathOrName.lastIndexOf('.')
  return dot >= 0 ? pathOrName.slice(dot).toLowerCase() : ''
}

export function isMountImagePath(path: string): boolean {
  const ext = mountPathExt(path)
  return ext !== '' && IMAGE_EXTS.has(ext)
}

export function isMountAudioPath(path: string): boolean {
  return AUDIO_EXTS.has(mountPathExt(path))
}

export function isMountVideoPath(path: string): boolean {
  return VIDEO_EXTS.has(mountPathExt(path))
}

export function isMountPlainPrePath(path: string): boolean {
  return PLAIN_PRE_EXTS.has(mountPathExt(path))
}

export function isMountMarkdownPath(path: string): boolean {
  return mountPathExt(path) === '.md'
}

export function isMountDirPath(path: string | null): boolean {
  return path !== null && mountPathExt(path) === ''
}

export function finalSegmentExt(pathOrName: string): string {
  const lastSlash = pathOrName.lastIndexOf('/')
  const base = lastSlash >= 0 ? pathOrName.slice(lastSlash + 1) : pathOrName
  const dot = base.lastIndexOf('.')
  return dot >= 0 ? base.slice(dot) : ''
}

export function stripFinalExt(pathOrName: string): string {
  const ext = finalSegmentExt(pathOrName)
  if (!ext) return pathOrName
  const lastSlash = pathOrName.lastIndexOf('/')
  const dir = lastSlash >= 0 ? pathOrName.slice(0, lastSlash + 1) : ''
  const base = lastSlash >= 0 ? pathOrName.slice(lastSlash + 1) : pathOrName
  return dir + base.slice(0, -ext.length)
}

export function appendFinalExt(pathOrName: string, ext: string): string {
  if (!ext) return pathOrName
  const lastSlash = pathOrName.lastIndexOf('/')
  const dir = lastSlash >= 0 ? pathOrName.slice(0, lastSlash + 1) : ''
  const base = lastSlash >= 0 ? pathOrName.slice(lastSlash + 1) : pathOrName
  return dir + base + ext
}

export function selectBasename(input: HTMLInputElement): void {
  const value = input.value
  const lastSlash = value.lastIndexOf('/')
  const start = lastSlash >= 0 ? lastSlash + 1 : 0
  input.setSelectionRange(start, value.length)
}
