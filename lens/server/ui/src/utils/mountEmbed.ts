/** Mirrors `lens.core.commands.attach.build_embed` (including HTML video tags). Replace-media uses this so VN “replace scene” edits match attach. */

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
const VIDEO_EXTS = new Set(['.mp4', '.webm', '.mov', '.avi'])
const PREVIEW_EXTS = new Set(['.md', '.txt'])

function pathExt(path: string): string {
  const seg = path.split('/').pop() ?? path
  const dot = seg.lastIndexOf('.')
  return dot >= 0 ? seg.slice(dot).toLowerCase() : ''
}

function encodeMountPath(path: string): string {
  // Encode path segments so spaces (and other reserved chars) produce valid URLs.
  // Keep `/` separators intact.
  return path
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/')
}

export function buildMountEmbedLine(relativePath: string): string {
  const path = relativePath.replace(/^\//, '')
  const fname = path.split('/').pop() ?? path
  const urlPath = encodeMountPath(path)
  const ext = pathExt(relativePath)
  if (IMAGE_EXTS.has(ext)) {
    return `![${fname}](/mount/file/${urlPath})`
  }
  if (VIDEO_EXTS.has(ext)) {
    return `<video src="/mount/file/${urlPath}" controls playsinline webkit-playsinline preload="metadata" style="max-width:100%"></video>`
  }
  if (PREVIEW_EXTS.has(ext)) {
    return `[${fname}](/mount/preview/${urlPath})`
  }
  return `[${fname}](/mount/file/${urlPath})`
}

function escapeHtmlAttr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

/** Mirrors `lens.core.commands.attach.build_layered_embed`. */
export function buildLayeredMountEmbedLine(bgRelativePath: string, fgRelativePath: string): string {
  const bgPath = bgRelativePath.replace(/^\//, '')
  const fgPath = fgRelativePath.replace(/^\//, '')
  const bgName = escapeHtmlAttr(bgPath.split('/').pop() ?? bgPath)
  const fgName = escapeHtmlAttr(fgPath.split('/').pop() ?? fgPath)
  const bgUrl = encodeMountPath(bgPath)
  const fgUrl = encodeMountPath(fgPath)
  return (
    `<div class="lens-vn-composite">` +
    `<img src="/mount/file/${bgUrl}" alt="${bgName}" class="lens-vn-bg">` +
    `<img src="/mount/file/${fgUrl}" alt="${fgName}" class="lens-vn-fg">` +
    `</div>`
  )
}
