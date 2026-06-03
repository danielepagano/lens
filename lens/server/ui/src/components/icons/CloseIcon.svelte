<script lang="ts">
  let { size = 18 }: { size?: number } = $props()
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  aria-hidden="true"
  focusable="false"
>
  <path
    d="M6 6L18 18M6 18L18 6"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
  />
</svg>

