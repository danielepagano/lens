import type { Page } from "playwright";
import type { SpellData } from "../types.js";

// Spell detail page: https://www.dndbeyond.com/spells/{slug}
//
// Confirmed selectors (verified 2026-03-04 against live DOM):
//   Spell name:        .page-title  (is an H1 element)
//   Stat block rows:   .ddb-statblock-item → .ddb-statblock-item-label / -value
//     labels: "Level", "Casting Time", "Range/Area", "Components", "Duration", "School"
//   Description:       .more-info-content  (contains <p> elements)
//   Higher level:      paragraph starting with "At Higher Levels" or "Using a Higher-Level..."
//
// Note: named functions inside page.evaluate are avoided because esbuild's keepNames
// transformation injects __name() calls that are not available in the browser context.

export async function parseSpellPage(page: Page): Promise<SpellData> {
  await page
    .waitForSelector(".ddb-statblock-item, .spell-details, .details-more-info", {
      timeout: 15000,
    })
    .catch(() => {
      throw new Error(`Spell page did not render stat block at ${page.url()}`);
    });

  return page.evaluate((): SpellData => {
    // Stat block: build label→value map (normalize whitespace in values)
    const stats: Record<string, string> = {};
    document.querySelectorAll(".ddb-statblock-item").forEach((item) => {
      const label =
        item.querySelector(".ddb-statblock-item-label")?.textContent?.trim().toLowerCase() ?? "";
      const rawValue =
        item.querySelector(".ddb-statblock-item-value")?.textContent ?? "";
      // Collapse internal whitespace (inner spans produce newlines)
      const value = rawValue.replace(/\s+/g, " ").trim();
      if (label) stats[label] = value;
    });

    // Name
    const name =
      document.querySelector(".page-title")?.textContent?.trim() ?? "";

    // Level
    let level = 0;
    const levelVal = stats["level"] ?? "";
    if (/cantrip/i.test(levelVal)) {
      level = 0;
    } else {
      const m = levelVal.match(/(\d+)/);
      if (m) level = parseInt(m[1]);
    }

    // School
    const school = (stats["school"] ?? "").toLowerCase() || "unknown";

    // Casting time, range, components, duration
    const castingTime = stats["casting time"] ?? stats["cast time"] ?? stats["casting"] ?? "unknown";
    const range = stats["range/area"] ?? stats["range"] ?? "unknown";
    const components = stats["components"] ?? stats["component"] ?? "unknown";
    const duration = stats["duration"] ?? "unknown";

    // Ritual detection
    const isRitual =
      components.toLowerCase().includes("ritual") ||
      !!document.querySelector(".ritual-tag, [class*='ritual']") ||
      (stats["ritual"]?.toLowerCase() === "yes");

    // Components blurb: material component footnote lives in .components-blurb
    // inside .more-info-content. Capture it and append to the components field.
    const compBlurb = document
      .querySelector(".more-info-content .components-blurb, .components-blurb")
      ?.textContent?.trim() ?? "";
    // Strip leading "* - " prefix that DnD Beyond adds
    const materialNote = compBlurb.replace(/^\*\s*-\s*/, "").trim();

    // Description: walk direct children of .more-info-content in document order,
    // rendering <p>, <ul>/<ol>, and <table> elements as plain text blocks.
    // Skip .components-blurb (handled above).
    const descEl =
      document.querySelector(".more-info-content") ??
      document.querySelector(".details-more-info");

    let description = "";
    let higherLevel: string | undefined;

    if (descEl) {
      const blocks: string[] = [];
      Array.from(descEl.children).forEach((el) => {
        // Skip the components footnote span
        if (el.classList.contains("components-blurb")) return;

        const tag = el.tagName.toUpperCase();

        if (tag === "P") {
          const t = el.textContent?.trim() ?? "";
          if (t) blocks.push(t);
        } else if (tag === "UL" || tag === "OL") {
          const items = Array.from(el.querySelectorAll("li")).map(
            (li) => "- " + (li.textContent?.trim() ?? "")
          );
          if (items.length) blocks.push(items.join("\n"));
        } else if (tag === "TABLE") {
          // Render as a simple Markdown table
          const rows: string[][] = [];
          el.querySelectorAll("tr").forEach((tr) => {
            const cells = Array.from(tr.querySelectorAll("th, td")).map(
              (cell) => cell.textContent?.trim() ?? ""
            );
            if (cells.length) rows.push(cells);
          });
          if (rows.length) {
            const tableLines = [
              "| " + rows[0].join(" | ") + " |",
              "| " + rows[0].map(() => "---").join(" | ") + " |",
              ...rows.slice(1).map((cols) => "| " + cols.join(" | ") + " |"),
            ];
            blocks.push(tableLines.join("\n"));
          }
        }
        // Other element types (divs, spans, etc.) are ignored
      });

      // Split at "At Higher Levels" block
      let hlIdx = -1;
      for (let i = 0; i < blocks.length; i++) {
        if (/^at higher levels|^using a higher-level spell slot/i.test(blocks[i])) {
          hlIdx = i;
          break;
        }
      }
      if (hlIdx >= 0) {
        description = blocks.slice(0, hlIdx).join("\n\n");
        const hlBlocks = blocks.slice(hlIdx);
        hlBlocks[0] = hlBlocks[0].replace(
          /^(at higher levels|using a higher-level spell slot)[.:]*\s*/i,
          ""
        );
        higherLevel = hlBlocks.join("\n\n");
      } else {
        description = blocks.join("\n\n");
      }
    }

    const slug = window.location.pathname.split("/").pop() ?? "";

    return {
      name: name || slug,
      slug,
      level,
      school,
      castingTime,
      range,
      components: materialNote ? components.replace(/\s*\*$/, "") + ` (${materialNote})` : components,
      duration,
      isRitual,
      description,
      higherLevel,
    };
  });
}
