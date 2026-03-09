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
      '/health': apiBase,
      '/stats': apiBase,
      '/tree': apiBase,
      '/node/': apiBase,
    },
  },
})
