<script lang="ts">
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { cancelCliRun } from '../../services/api'
  import { cliOutput } from '../../stores/ui'

  const DEFAULT_TITLE = 'CLI output'

  export let title: string = DEFAULT_TITLE
  export let autoClose = false

  $: isOpen = $cliOutput !== null
  $: isStreaming = $cliOutput?.streaming ?? false
  $: isError = $cliOutput !== null && $cliOutput.exitCode !== null && $cliOutput.exitCode !== 0
  $: panelTheme = isError ? 'error' as const : 'cli' as const
  $: displayTitle = isError ? 'Error' : title

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
  title={displayTitle}
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

