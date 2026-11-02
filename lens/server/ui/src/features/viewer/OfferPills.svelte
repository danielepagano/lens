<script lang="ts">
  /**
   * Held-back parts offered at the cursor (see `core/triggers.py`).
   *
   * Prep declares triggers; the play model, or a closing design session,
   * offers one by writing `<!-- suggest:<slug> -->` into the passage. A
   * trigger's `run` is an ordinary command line, so both buttons go through
   * the command bar exactly as the CLI's `Run <slug>? [Y/n/e]` does: **Run**
   * submits it, **Edit** puts it in the bar to change first. Either way the
   * next submission carries the slug, which names the session `<slug>-tr`.
   */
  import type { TriggerOffer } from '../../services/api'
  import { cliInputRequest, cliSubmitRequest, pendingTrigger } from '../../stores/ui'

  let { offers = [] }: { offers?: TriggerOffer[] } = $props()

  function commandLine(offer: TriggerOffer): string {
    const run = offer.run.trim().replace(/^lens\s+/, '')
    return run.startsWith('/') ? run : `/${run}`
  }

  function run(offer: TriggerOffer): void {
    pendingTrigger.set(offer.slug)
    cliSubmitRequest.set(commandLine(offer))
  }

  function edit(offer: TriggerOffer): void {
    pendingTrigger.set(offer.slug)
    cliInputRequest.set(commandLine(offer))
  }
</script>

{#if offers.length > 0}
  <div class="offer-pills" data-testid="cursor-offer-pills">
    {#each offers as offer (offer.slug)}
      <div class="offer" data-testid="cursor-offer">
        <span class="offer-label" title={`declared on ${offer.declared_on}`}>
          Held back: <strong>{offer.slug}</strong> — {offer.when}
        </span>
        <button type="button" class="offer-btn" title={offer.run} onclick={() => run(offer)}>Run</button>
        <button
          type="button"
          class="offer-btn secondary"
          title="Put the command in the bar to edit before running"
          onclick={() => edit(offer)}>Edit</button
        >
      </div>
    {/each}
  </div>
{/if}

<style>
  .offer-pills {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin: 0.5rem 0;
  }
  .offer {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    padding: 0.35rem 0.6rem;
    border: 1px dashed var(--pico-primary-border, currentColor);
    border-radius: 0.5rem;
    font-size: 0.85rem;
  }
  .offer-label {
    flex: 1 1 12rem;
  }
  .offer-btn {
    width: auto;
    margin: 0;
    padding: 0.15rem 0.6rem;
    font-size: 0.8rem;
  }
</style>
