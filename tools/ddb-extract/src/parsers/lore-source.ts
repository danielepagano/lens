import type { Page } from "playwright";

export interface LoreTocEntry {
  href: string;
  title: string;
  chapterNumber?: number;
  /** Optional part/section heading this chapter belongs to (from H2). */
  partTitle?: string;
  /** Optional subsections listed under this chapter in the TOC. */
  subsections?: { title: string; href: string }[];
}

/**
 * Parse the table-of-contents section from a D&D Beyond sourcebook page.
 *
 * Works against pages like:
 *   https://www.dndbeyond.com/sources/dnd/ghcg
 *
 * It targets the main TOC container:
 *   .compendium-toc-full-text
 *
 * and extracts all top-level chapter links rendered as:
 *   <h3><a href="/sources/dnd/ghcg/magic-in-etharis">Chapter 12: Magic in Etharis</a></h3>
 */
export async function parseLoreToc(page: Page): Promise<LoreTocEntry[]> {
  await page
    .waitForSelector(".compendium-toc-full-text h3 a", {
      timeout: 20000,
    })
    .catch(() => {
      throw new Error(`Lore TOC did not render at ${page.url()}`);
    });

  return page.evaluate((): LoreTocEntry[] => {
    const container = document.querySelector(".compendium-toc-full-text");
    if (!container) return [];

    const results: LoreTocEntry[] = [];
    let currentPartTitle: string | undefined;

    const children = Array.from(container.children);
    for (let i = 0; i < children.length; i++) {
      const el = children[i];
      if (!(el instanceof HTMLElement)) continue;
      const tag = el.tagName.toUpperCase();

      if (tag === "H2") {
        const partAnchor = el.querySelector("a");
        const partText = (partAnchor?.textContent ?? el.textContent ?? "").trim();
        currentPartTitle = partText || undefined;
        continue;
      }

      if (tag === "H3") {
        const a = el.querySelector("a[href]");
        if (!a) continue;
        const href = a.getAttribute("href") ?? "";
        const rawTitle = a.textContent?.trim() ?? "";
        if (!href || !rawTitle) continue;

        let chapterNumber: number | undefined;
        let title = rawTitle;

        const m = rawTitle.match(/^Chapter\s+(\d+):\s*(.+)$/i);
        if (m) {
          chapterNumber = parseInt(m[1], 10);
          title = m[2].trim();
        }

        const entry: LoreTocEntry = {
          href,
          title,
          chapterNumber: Number.isFinite(chapterNumber) ? chapterNumber : undefined,
          partTitle: currentPartTitle,
        };

        // Look for immediate following UL containing chapter subsections
        const next = children[i + 1];
        if (next instanceof HTMLElement && next.tagName.toUpperCase() === "UL") {
          const subs: { title: string; href: string }[] = [];
          next.querySelectorAll("li a[href]").forEach((subA) => {
            const sHref = subA.getAttribute("href") ?? "";
            const sTitle = subA.textContent?.trim() ?? "";
            if (!sHref || !sTitle) return;
            subs.push({ title: sTitle, href: sHref });
          });
          if (subs.length) entry.subsections = subs;
        }

        results.push(entry);
      }
    }

    return results;
  });
}

