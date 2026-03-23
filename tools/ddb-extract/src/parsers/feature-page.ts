import type { Page } from "playwright";
import type { FeatureData, FeatureParentKind } from "../types.js";
import { normalizeFeatureName, toFeatureSlug } from "../formatters/kb.js";

export async function parseFeaturePage(
  page: Page,
  kind: FeatureParentKind
): Promise<FeatureData[]> {
  await page
    .waitForSelector("section.primary-content, h1, .page-title", {
      timeout: 30000,
      state: "attached",
    })
    .catch(() => {
      throw new Error(`Feature detail page did not render at ${page.url()}`);
    });

  return page.evaluate(
    ({ featureKind }): FeatureData[] => {
      const primary =
        document.querySelector<HTMLElement>("section.primary-content") ?? document.body;
      const h1 =
        document.querySelector<HTMLElement>("h1[id$='ClassDetails']") ??
        document.querySelector<HTMLElement>("h1[id$='RaceDetails']") ??
        document.querySelector<HTMLElement>("h1[id$='SpeciesDetails']") ??
        document.querySelector<HTMLElement>("h1.page-title") ??
        document.querySelector<HTMLElement>("h1");
      const parentName =
        h1?.childNodes[0]?.textContent?.trim() || h1?.textContent?.trim() || "unknown";

      const match = window.location.pathname.match(
        /^\/(classes|species)\/(\d+)-([a-z0-9-]+)(?:\/)?$/i
      );
      const parentSlug = match?.[3] ?? "unknown";
      const parentKind = featureKind;
      const sourceUrl = window.location.href;

      const headings = Array.from(primary.querySelectorAll<HTMLElement>("h4"));
      const results: FeatureData[] = [];
      headings.forEach((h4, idx) => {
        const rawName = h4.textContent?.replace(/\s+/g, " ").trim() ?? "";
        const cleaned =
          parentKind === "class"
            ? rawName.replace(/^Level\s*(?:\(\s*\d+\s*\)|\d+)\s*:\s*/i, "").trim()
            : rawName.trim();
        if (!cleaned) return;
        const subclassContainer = h4.closest(".subitems-list-details-item");
        const subclassRaw =
          subclassContainer?.querySelector<HTMLElement>("h2")?.textContent?.replace(/\s+/g, " ").trim() ??
          "";
        const subclassContentSlug =
          subclassContainer?.querySelector<HTMLElement>("h2[data-content-slug]")?.dataset.contentSlug ??
          undefined;
        const subclassName = subclassRaw || undefined;
        const subclassSlug = subclassName
          ? subclassName
              .toLowerCase()
              .replace(/[’']/g, "")
              .replace(/[^a-z0-9]+/g, "-")
              .replace(/^-+|-+$/g, "")
          : undefined;
        const fragment = document.createDocumentFragment();
        let cursor = h4.nextSibling;
        while (cursor) {
          if (cursor.nodeType === Node.ELEMENT_NODE) {
            const el = cursor as Element;
            const tag = el.tagName.toUpperCase();
            if (tag === "H2" || tag === "H3" || tag === "H4") break;
            if (
              el.matches("#comments, .comments, .comments-container, .forums-posts, script")
            ) {
              break;
            }
          }
          fragment.appendChild(cursor.cloneNode(true));
          cursor = cursor.nextSibling;
        }
        const bodyBlocks: string[] = [];
        const pending = Array.from(fragment.childNodes);
        while (pending.length > 0) {
          const node = pending.shift();
          if (!node) continue;
          if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent?.replace(/\s+/g, " ").trim() ?? "";
            if (text) bodyBlocks.push(text);
            continue;
          }
          if (node.nodeType !== Node.ELEMENT_NODE) continue;
          const el = node as Element;
          const tag = el.tagName.toUpperCase();
          if (tag === "P") {
            let text = el.innerHTML;
            text = text
              .replace(/<(strong|b)\b[^>]*>([\s\S]*?)<\/\1>/gi, "**$2**")
              .replace(/<(em|i)\b[^>]*>([\s\S]*?)<\/\1>/gi, "*$2*")
              .replace(/<a\b[^>]*>([\s\S]*?)<\/a>/gi, "$1")
              .replace(/<br\s*\/?>/gi, "\n")
              .replace(/<[^>]+>/g, "");
            const decoder = document.createElement("textarea");
            decoder.innerHTML = text;
            text = decoder.value.replace(/\s+/g, " ").trim();
            if (text) bodyBlocks.push(text);
            continue;
          }
          if (tag === "UL" || tag === "OL") {
            const lines: string[] = [];
            let n = 1;
            el.querySelectorAll(":scope > li").forEach((li) => {
              let text = li.innerHTML;
              text = text
                .replace(/<(strong|b)\b[^>]*>([\s\S]*?)<\/\1>/gi, "**$2**")
                .replace(/<(em|i)\b[^>]*>([\s\S]*?)<\/\1>/gi, "*$2*")
                .replace(/<a\b[^>]*>([\s\S]*?)<\/a>/gi, "$1")
                .replace(/<br\s*\/?>/gi, "\n")
                .replace(/<[^>]+>/g, "");
              const decoder = document.createElement("textarea");
              decoder.innerHTML = text;
              text = decoder.value.replace(/\s+/g, " ").trim();
              if (!text) return;
              lines.push(tag === "OL" ? `${n}. ${text}` : `- ${text}`);
              n += 1;
            });
            if (lines.length) bodyBlocks.push(lines.join("\n"));
            continue;
          }
          if (tag === "TABLE") {
            const rows: string[][] = [];
            const caption = el.querySelector("caption")?.textContent?.replace(/\s+/g, " ").trim() ?? "";
            el.querySelectorAll("tr").forEach((tr) => {
              const cols = Array.from(tr.querySelectorAll("th, td"))
                .map((cell) => cell.textContent?.replace(/\s+/g, " ").trim() ?? "")
                .filter(Boolean);
              if (cols.length > 0) rows.push(cols);
            });
            if (rows.length > 0) {
              const header = `| ${rows[0].join(" | ")} |`;
              const divider = `| ${rows[0].map(() => "---").join(" | ")} |`;
              const body = rows.slice(1).map((r) => `| ${r.join(" | ")} |`);
              const tableMd = [header, divider, ...body].join("\n");
              bodyBlocks.push(caption ? `**${caption}**\n\n${tableMd}` : tableMd);
            }
            continue;
          }
          if (tag === "H5" || tag === "H6") {
            let text = el.innerHTML;
            text = text
              .replace(/<(strong|b)\b[^>]*>([\s\S]*?)<\/\1>/gi, "**$2**")
              .replace(/<(em|i)\b[^>]*>([\s\S]*?)<\/\1>/gi, "*$2*")
              .replace(/<a\b[^>]*>([\s\S]*?)<\/a>/gi, "$1")
              .replace(/<br\s*\/?>/gi, "\n")
              .replace(/<[^>]+>/g, "");
            const decoder = document.createElement("textarea");
            decoder.innerHTML = text;
            text = decoder.value.replace(/\s+/g, " ").trim();
            if (text) bodyBlocks.push(tag === "H5" ? `### ${text}` : `#### ${text}`);
            continue;
          }
          if (tag === "BLOCKQUOTE") {
            let text = el.innerHTML;
            text = text
              .replace(/<(strong|b)\b[^>]*>([\s\S]*?)<\/\1>/gi, "**$2**")
              .replace(/<(em|i)\b[^>]*>([\s\S]*?)<\/\1>/gi, "*$2*")
              .replace(/<a\b[^>]*>([\s\S]*?)<\/a>/gi, "$1")
              .replace(/<br\s*\/?>/gi, "\n")
              .replace(/<[^>]+>/g, "");
            const decoder = document.createElement("textarea");
            decoder.innerHTML = text;
            text = decoder.value.replace(/\s+/g, " ").trim();
            if (text) bodyBlocks.push(`> ${text}`);
            continue;
          }
          const children = Array.from(el.childNodes);
          for (let i = children.length - 1; i >= 0; i -= 1) {
            pending.unshift(children[i]);
          }
        }
        const body = bodyBlocks.join("\n\n").trim();
        if (!body) return;

        results.push({
          parentKind,
          parentSlug,
          parentName,
          subclassName,
          subclassSlug,
          subclassContentSlug,
          featureName: cleaned,
          featureSlug: cleaned
            .toLowerCase()
            .replace(/[’']/g, "")
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, ""),
          body,
          sourceUrl,
        });
      });

      return results;
    },
    { featureKind: kind }
  ).then((items) =>
    items.map((item) => ({
      ...item,
      featureName: normalizeFeatureName(item.featureName, kind),
      featureSlug: toFeatureSlug(item.featureName),
    }))
  );
}
