<script lang="ts">
  import { onMount } from 'svelte'
  import { kbDetailId } from '../../stores/ui'
  import { currentProject } from '../../stores/project'
  import { stats } from '../../stores/stats'
  import { getKbItem } from '../../services/api'
  import type { KbItemDetail } from '../../services/api'
  import {
    attachKbDetailClicks,
    renderKbMarkdown,
    setKbDetailParam,
  } from './kbViewerMarkdown'
  import type { KbLinkHandler } from './kbViewerMarkdown'

  let item = $state.raw<KbItemDetail | null>(null)
  let loadError = $state('')
  let activeLoadSeq = 0

  const rendered = $derived(
    item
      ? renderKbMarkdown(item.content, $stats?.remember_pins_at_cursor ?? undefined, $currentProject).html
      : '',
  )

  const handler: KbLinkHandler = (id: string) => {
    kbDetailId.set(id)
    setKbDetailParam(id)
  }

  const markdownClickAttach = $derived(attachKbDetailClicks(handler))

  async function loadItem(id: string, loadSeq: number) {
    loadError = ''
    try {
      const nextItem = await getKbItem(id)
      if (loadSeq !== activeLoadSeq) return
      item = nextItem
    } catch (e) {
      if (loadSeq !== activeLoadSeq) return
      loadError = String(e)
      item = null
    }
  }

  onMount(() => {
    return kbDetailId.subscribe((id) => {
      activeLoadSeq += 1
      const loadSeq = activeLoadSeq
      if (!id) {
        item = null
        loadError = ''
        return
      }
      void loadItem(id, loadSeq)
    })
  })

  function close() {
    kbDetailId.set(null)
    setKbDetailParam(null)
  }
</script>

<div class="kb-detail-view">
  <div class="kb-detail-header">
    <span class="kb-detail-id">
      {#if loadError}
        {loadError}
      {:else if item}
        {item.id}
      {:else}
        Loading…
      {/if}
    </span>
    <button type="button" class="kb-detail-close" onclick={close} aria-label="Close detail pane">
      &times;
    </button>
  </div>
  {#if item && !loadError}
    <article class="content kb-rendered kb-detail-body">
      <div class="kb-rendered-md" {@attach markdownClickAttach}>
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown renderer -->
        {@html rendered}
      </div>
    </article>
  {/if}
</div>
