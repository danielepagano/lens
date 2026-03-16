import type { Page } from "playwright";

export interface LoreChapterData {
  title: string;
  slug: string;
  body: string;
}

/**
 * Parse a lore chapter detail page into a markdown-ish body.
 *
 * Targets pages like:
 *   https://www.dndbeyond.com/sources/dnd/ghcg/magic-in-etharis
 *
 * Main content container:
 *   .p-article-content.u-typography-format
 */
export async function parseLoreChapterPage(page: Page): Promise<LoreChapterData> {
  await page
    .waitForSelector(".p-article-content.u-typography-format", {
      timeout: 20000,
    })
    .catch(() => {
      throw new Error(`Lore chapter page did not render at ${page.url()}`);
    });

  return page.evaluate((): LoreChapterData => {
    const container = document.querySelector<HTMLDivElement>(
      ".p-article-content.u-typography-format"
    );
    if (!container) {
      const slug = window.location.pathname.split("/").pop() ?? "";
      return {
        title: document.title || slug || "Untitled",
        slug,
        body: "",
      };
    }

    const blocks: string[] = [];
    Array.from(container.children).forEach((child) => {
      if (!(child instanceof HTMLElement)) return;
      // Skip the jump menu select; it duplicates heading structure
      if (child.matches("select.nav-select")) return;
      const tag = child.tagName.toUpperCase();

      let block: string | null = null;

      if (tag === "P") {
        const t = (child.textContent ?? "").replace(/\s+/g, " ").trim();
        block = t || null;
      } else if (tag === "H1" || tag === "H2" || tag === "H3" || tag === "H4") {
        const level = tag === "H1" ? "#" : tag === "H2" ? "##" : tag === "H3" ? "###" : "####";
        const t = (child.textContent ?? "").replace(/\s+/g, " ").trim();
        block = t ? `${level} ${t}` : null;
      } else if (tag === "UL" || tag === "OL") {
        const items: string[] = [];
        child.querySelectorAll("li").forEach((li) => {
          const t = (li.textContent ?? "").replace(/\s+/g, " ").trim();
          if (t) items.push(`- ${t}`);
        });
        block = items.length ? items.join("\n") : null;
      } else if (tag === "FIGURE") {
        const caption = child.querySelector("figcaption")?.textContent?.trim() ?? "";
        const fallback = (child.textContent ?? "").replace(/\s+/g, " ").trim();
        block = caption || (fallback || null);
      } else if (tag === "ASIDE") {
        const inner = (child.textContent ?? "").trim();
        block = inner ? `> ${inner.replace(/\n+/g, "\n> ")}` : null;
      } else if (tag === "TABLE") {
        const rows: string[][] = [];
        child.querySelectorAll("tr").forEach((tr) => {
          const cells = Array.from(tr.querySelectorAll("th, td")).map((cell) =>
            (cell.textContent ?? "").replace(/\s+/g, " ").trim()
          );
          if (cells.length) rows.push(cells);
        });
        if (rows.length) {
          const header = rows[0];
          const tableLines = [
            "| " + header.join(" | ") + " |",
            "| " + header.map(() => "---").join(" | ") + " |",
            ...rows.slice(1).map((cols) => "| " + cols.join(" | ") + " |"),
          ];
          block = tableLines.join("\n");
        }
      } else {
        const text = (child.textContent ?? "").replace(/\s+/g, " ").trim();
        block = text || null;
      }

      if (block) blocks.push(block);
    });

    const slug = window.location.pathname.split("/").pop() ?? "";
    const heading =
      container.querySelector("h1, h2")?.textContent?.trim() ??
      document.querySelector(".page-title")?.textContent?.trim() ??
      document.title;

    return {
      title: heading || slug || "Untitled",
      slug,
      body: blocks.join("\n\n"),
    };
  });
}

