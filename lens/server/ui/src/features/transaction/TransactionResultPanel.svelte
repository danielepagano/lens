<script lang="ts">
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { transactionResult } from '../../stores/ui'

  const isOpen = $derived($transactionResult !== null)
  const title = $derived($transactionResult?.title ?? 'Transaction')
  const message = $derived($transactionResult?.message ?? '')
  const panelTheme = $derived(
    ($transactionResult?.theme === 'info' ? 'command' : 'error') as 'command' | 'error',
  )

  function handleClose() {
    transactionResult.set(null)
  }
</script>

<OutputPanel
  {title}
  theme={panelTheme}
  open={isOpen}
  streaming={false}
  autoClose={false}
  hasContent={true}
  showCancel={false}
  onClose={handleClose}
>
  {#snippet content()}
    <pre class="transaction-result-content">{message || ' '}</pre>
  {/snippet}
</OutputPanel>

