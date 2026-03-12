import '@picocss/pico/css/pico.min.css'
import './app.css'
import App from './App.svelte'

// Hard-lock UI to dark mode for consistent readability.
if (typeof document !== 'undefined') {
  document.documentElement.setAttribute('data-theme', 'dark')
}

const app = new App({ target: document.getElementById('app')! })
export default app
