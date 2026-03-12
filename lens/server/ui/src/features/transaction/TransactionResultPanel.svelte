<script lang="ts">
  import OutputPanel from '../../components/OutputPanel.svelte'
  import { transactionResult } from '../../stores/ui'

  $: isOpen = $transactionResult !== null
  $: title = $transactionResult?.title ?? 'Transaction'
  $: message = $transactionResult?.message ?? ''

  function handleClose() {
    transactionResult.set(null)
  }
</script>

<OutputPanel
  {title}
  theme="error"
  open={isOpen}
  streaming={false}
  autoClose={false}
  hasContent={true}
  showCancel={false}
  on:close={handleClose}
>
  <pre slot="content" class="transaction-result-content">{message || ' '}</pre>
</OutputPanel>

