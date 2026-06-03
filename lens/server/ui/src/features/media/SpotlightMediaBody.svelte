<script lang="ts">
  import { getMountFilePath, getMountPreviewPath } from '../../services/api'

  type Props = {
    path?: string | null
    filename?: string
    imageSrc?: string
    isAudio?: boolean
    isVideo?: boolean
    isPlainPre?: boolean
    isMarkdownPreview?: boolean
    isDir?: boolean
    plainPreviewLoading?: boolean
    plainPreviewError?: string | null
    plainPreviewText?: string
  }

  let {
    path = null,
    filename = '',
    imageSrc = '',
    isAudio = false,
    isVideo = false,
    isPlainPre = false,
    isMarkdownPreview = false,
    isDir = false,
    plainPreviewLoading = false,
    plainPreviewError = null,
    plainPreviewText = '',
  }: Props = $props()
</script>

{#if isAudio}
  <audio src={imageSrc} controls preload="metadata" class="spotlight-audio"></audio>
{:else if isVideo && path}
  <!-- svelte-ignore a11y_media_has_caption -->
  <video
    src={getMountFilePath(path)}
    controls
    playsinline
    preload="metadata"
    class="spotlight-video"
  ></video>
{:else if isPlainPre}
  <div class="spotlight-plain-wrap">
    {#if plainPreviewLoading}
      <span class="carousel-spotlight-placeholder">Loading…</span>
    {:else if plainPreviewError}
      <span class="carousel-spotlight-placeholder" role="alert">{plainPreviewError}</span>
    {:else}
      <pre class="spotlight-plain">{plainPreviewText}</pre>
    {/if}
  </div>
{:else if isMarkdownPreview && path}
  <iframe
    src={getMountPreviewPath(path)}
    title={filename}
    class="spotlight-iframe"
    sandbox="allow-scripts allow-same-origin"
  ></iframe>
{:else if isDir}
  <span class="carousel-spotlight-placeholder">📁 {filename}</span>
{:else}
  <span class="carousel-spotlight-placeholder">📄 {filename}</span>
{/if}

<style>
  .spotlight-iframe,
  .spotlight-video,
  .spotlight-audio {
    flex: 1;
    min-height: 0;
    width: 100%;
    border: none;
    border-radius: 0;
  }
  .spotlight-audio {
    align-self: center;
    max-height: 4rem;
  }
  .spotlight-plain-wrap {
    flex: 1;
    min-height: 0;
    width: 100%;
    overflow: auto;
    padding: 0.5rem 0.75rem;
    box-sizing: border-box;
  }
  .spotlight-plain {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.8rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
