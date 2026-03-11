// @ts-nocheck
import { defineConfig } from 'vite'
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte'

const apiHost = process.env.VITE_API_HOST ?? '127.0.0.1'
const apiPort = process.env.VITE_API_PORT ?? '8000'
const apiBase = `http://${apiHost}:${apiPort}`

export default defineConfig({
  plugins: [svelte({ preprocess: vitePreprocess() })],
  build: {
    outDir: '../static',
    emptyOutDir: true,
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
