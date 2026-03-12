<script lang="ts">
  import { get } from 'svelte/store'
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { cancelCliRun } from '../../services/api'
  import { cliOutput } from '../../stores/ui'

  const DEFAULT_TITLE = 'CLI output'

  export let title: string = DEFAULT_TITLE
  export let autoClose = false

  $: isOpen = $cliOutput !== null
  $: isStreaming = $cliOutput?.streaming ?? false
  $: panelTheme = resolveTheme()

  function resolveTheme(): 'cli' | 'error' | 'command' {
    if ($cliOutput && $cliOutput.exitCode !== null && $cliOutput.exitCode !== 0) {
      return 'error'
    }
    return 'cli'
  }

  async function handleCancel() {
    try {
      await cancelCliRun()
    } catch (e) {
      console.error('Cancel failed:', e)
    }
  }

  function handleClose() {
    cliOutput.set(null)
  }
</script>

<OutputPanel
  {title}
  theme={panelTheme}
  open={isOpen}
  streaming={isStreaming}
  {autoClose}
  hasContent={true}
  showCancel={isStreaming}
  on:cancel={handleCancel}
  on:close={handleClose}
>
  <pre slot="content" class="cli-output-content">{$cliOutput?.output || ' '}</pre>
</OutputPanel>

