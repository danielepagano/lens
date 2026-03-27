// @ts-nocheck
import { resolve } from 'path'
import { defineConfig } from 'vite'
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte'

const apiHost = process.env.VITE_API_HOST ?? '127.0.0.1'
const apiPort = process.env.VITE_API_PORT ?? '8000'
const apiBase = `http://${apiHost}:${apiPort}`

export default defineConfig({
  plugins: [svelte({ preprocess: vitePreprocess(), prebundleSvelteLibraries: false })],
  build: {
    outDir: '../static',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        preview: resolve(__dirname, 'preview.html'),
      },
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('@lezer')) return 'lezer'
          if (id.includes('@codemirror') || id.includes('node_modules/codemirror/')) {
            return 'codemirror'
          }
        },
      },
    },
  },
  server: {
    proxy: {
      '/': {
        target: apiBase,
        changeOrigin: true,
        bypass(req) {
          const url = req.url ?? '/'
          const accept = req.headers?.accept ?? ''
          const upgrade = req.headers?.upgrade ?? ''

          // Preview sub-app: serve preview.html from the Vite dev server.
          if (url.startsWith('/mount/preview/')) return '/preview.html'

          // All other mount requests proxy to the backend (file downloads send Accept: text/html).
          if (url.startsWith('/mount/')) return null

          // Let Vite serve the UI shell + HMR/internal assets.
          if (
            upgrade.toLowerCase() === 'websocket' ||
            accept.includes('text/html') ||
            url.startsWith('/@') ||
            url.startsWith('/src/') ||
            url.startsWith('/node_modules/') ||
            url.startsWith('/__') ||
            url.startsWith('/favicon')
          ) {
            return url
          }

          // Everything else (API calls) goes to the backend.
          return null
        },
      },
    },
  },
})
