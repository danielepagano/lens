<script lang="ts">
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { cancelStream } from '../../services/api'
  import { cliOutput } from '../../stores/ui'

  const DEFAULT_TITLE = 'CLI output'

  type Props = {
    title?: string
    autoClose?: boolean
  }

  let { title = DEFAULT_TITLE, autoClose = false }: Props = $props()

  const isOpen = $derived($cliOutput !== null)
  const isStreaming = $derived($cliOutput?.streaming ?? false)
  const isError = $derived(
    $cliOutput !== null && $cliOutput.exitCode !== null && $cliOutput.exitCode !== 0,
  )
  const panelTheme = $derived(isError ? 'error' : 'cli')
  const displayTitle = $derived(isError ? 'Error' : title)

  async function handleCancel() {
    try {
      await cancelStream()
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
  onCancel={handleCancel}
  onClose={handleClose}
>
  {#snippet content()}
    <pre class="cli-output-content">{$cliOutput?.output || ' '}</pre>
  {/snippet}
</OutputPanel>

