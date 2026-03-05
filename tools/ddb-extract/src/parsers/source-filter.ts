import type { Page } from "playwright";

// Reads the hidden <select id="filter-source"> that DnD Beyond renders on all
// list pages (/spells, /monsters, /magic-items, /equipment).
//
// The select is always present in the DOM on page load — no interaction or
// "Show Advanced Filters" click required. All four list pages return the same
// 136 sources, so we only need to load one page.
//
// Selector confirmed 2026-03-04 on all four list page types.

export interface DiscoveredSource {
  name: string;
  filterId: number;
}

export async function discoverSources(
  page: Page,
  verbose: boolean
): Promise<DiscoveredSource[]> {
  const url = "https://www.dndbeyond.com/spells";
  if (verbose) console.log(`  [source-filter] GET ${url}`);

  await page.goto(url, { waitUntil: "networkidle" });

  const sources = await page.evaluate((): Array<{ name: string; filterId: number }> => {
    const sel = document.querySelector<HTMLSelectElement>("select#filter-source");
    if (!sel) return [];
    return Array.from(sel.options)
      .map((o) => ({ name: o.text.trim(), filterId: parseInt(o.value, 10) }))
      .filter((s) => s.filterId > 0 && s.name.length > 0);
  });

  if (verbose) console.log(`  [source-filter] found ${sources.length} source(s)`);
  return sources;
}
