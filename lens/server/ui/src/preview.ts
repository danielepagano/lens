import MarkdownIt from 'markdown-it'

const filePath = window.location.pathname.replace(/^\/mount\/preview\//, '')
const container = document.getElementById('content')!

if (!filePath) {
  container.textContent = 'No file path specified.'
} else {
  document.title = filePath.split('/').pop() ?? filePath

  fetch(`/mount/file/${filePath}`)
    .then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      return r.text()
    })
    .then((text) => {
      const md = new MarkdownIt({ html: false, linkify: true, typographer: true })
      container.innerHTML = md.render(text)
    })
    .catch((err: unknown) => {
      container.textContent =
        `Could not load "${filePath}": ${err instanceof Error ? err.message : String(err)}`
    })
}
