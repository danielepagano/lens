import '@picocss/pico/css/pico.min.css'
import './app.css'
import { mount } from 'svelte'
import App from './App.svelte'

// Hard-lock UI to dark mode for consistent readability.
if (typeof document !== 'undefined') {
  document.documentElement.setAttribute('data-theme', 'dark')
}

const app = mount(App, { target: document.getElementById('app')! })
export default app
