import type { Page } from "playwright";
import type { ItemData } from "../types.js";

// Magic item detail page: https://www.dndbeyond.com/magic-items/{slug}
//
// Confirmed selectors (verified 2026-03-04 against live DOM):
//   Item name:     .page-title  (is an H1 element)
//   Subtitle:      .item-info .details  ("Wondrous Item, very rare")
//   Attunement:    subtitle text contains "Requires Attunement"
//   Description:   .more-info-content
//
// IMPORTANT: do not use named function variables inside page.evaluate —
// esbuild's keepNames injects __name() calls undefined in the browser context.

export async function parseItemPage(page: Page): Promise<ItemData> {
  await page
    .waitForSelector(".item-details, .more-info-content", {
      timeout: 15000,
    })
    .catch(() => {
      throw new Error(`Item page did not render at ${page.url()}`);
    });

  return page.evaluate((): ItemData => {
    const name = document.querySelector(".page-title")?.textContent?.trim() ?? "";
    const slug = window.location.pathname.split("/").pop() ?? "";

    // Subtitle: "Wondrous Item, very rare" or "Ring, Rare (Requires Attunement)"
    const subtitle =
      document.querySelector(".item-info .details")?.textContent?.trim() ??
      document.querySelector(".item-subtitle")?.textContent?.trim() ??
      "";

    // Item type: first part before comma or parenthesis
    const typePart = subtitle.split(",")[0].trim().split("(")[0].trim();
    const itemType = typePart.toLowerCase().replace(/\s+/g, "-") || "unknown";

    // Rarity
    const rarityMatch = subtitle.match(
      /\b(common|uncommon|rare|very rare|legendary|artifact|varies)\b/i
    );
    const rarity = rarityMatch
      ? rarityMatch[1].toLowerCase().replace(/\s+/g, "-")
      : "unknown";

    // Attunement
    const requiresAttunement =
      subtitle.toLowerCase().includes("requires attunement") ||
      !!document.querySelector("[class*='attunement']");

    // Description
    const descEl =
      document.querySelector(".more-info-content") ??
      document.querySelector(".details-more-info");
    const description = descEl?.textContent?.trim() ?? "";

    return {
      name: name || slug,
      slug,
      rarity,
      itemType,
      requiresAttunement,
      description,
    };
  });
}
