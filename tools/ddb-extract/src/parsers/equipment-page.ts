import type { Page } from "playwright";
import type { EquipmentData } from "../types.js";

// Equipment detail page: https://www.dndbeyond.com/equipment/{slug}
//
// Confirmed selectors (verified 2026-03-04 against live DOM):
//   Equipment name:  .page-title  (is an H1 element)
//   Stat rows:       .ddb-statblock-item → label / value (Cost, Damage, Weight, Properties)
//   Description:     .more-info-content
//
// IMPORTANT: do not use named function variables inside page.evaluate —
// esbuild's keepNames injects __name() calls undefined in the browser context.

export async function parseEquipmentPage(page: Page): Promise<EquipmentData> {
  await page
    .waitForSelector(".ddb-statblock-item, .more-info-content, .equipment-details", {
      timeout: 15000,
    })
    .catch(() => {
      throw new Error(`Equipment page did not render at ${page.url()}`);
    });

  return page.evaluate((): EquipmentData => {
    const name = document.querySelector(".page-title")?.textContent?.trim() ?? "";
    const slug = window.location.pathname.split("/").pop() ?? "";

    // Category from item-info or subtitle
    const subtitle =
      document.querySelector(".item-info .details")?.textContent?.trim() ??
      document.querySelector(".equipment-type")?.textContent?.trim() ??
      "";
    const category = subtitle.toLowerCase().replace(/\s+/g, "-") || "unknown";

    // Stat rows
    const stats: Record<string, string> = {};
    document.querySelectorAll(".ddb-statblock-item").forEach((item) => {
      const label =
        item.querySelector(".ddb-statblock-item-label")?.textContent?.trim().toLowerCase() ?? "";
      const value =
        item.querySelector(".ddb-statblock-item-value")?.textContent?.trim() ?? "";
      if (label) stats[label] = value;
    });

    const cost = stats["cost"] ?? stats["price"] ?? undefined;
    const damage = stats["damage"] ?? undefined;
    const weight = stats["weight"] ?? undefined;
    const properties = stats["properties"] ?? stats["property"] ?? undefined;

    const descEl =
      document.querySelector(".more-info-content") ??
      document.querySelector(".details-more-info");
    const description = descEl?.textContent?.trim() ?? "";

    return {
      name: name || slug,
      slug,
      category,
      cost,
      damage,
      weight,
      properties,
      description,
    };
  });
}
