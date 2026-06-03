<script lang="ts">
  let { size = 20 }: { size?: number } = $props()
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  aria-hidden="true"
  focusable="false"
>
  <rect x="3" y="6" width="18" height="2" rx="1" fill="currentColor" />
  <rect x="3" y="11" width="18" height="2" rx="1" fill="currentColor" />
  <rect x="3" y="16" width="18" height="2" rx="1" fill="currentColor" />
</svg>

