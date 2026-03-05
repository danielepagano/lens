import type { Page } from "playwright";
import type { EquipmentData } from "../types.js";

// Equipment detail page: https://www.dndbeyond.com/equipment/{slug}
//
// Two DOM variants:
// 1) Legacy: .ddb-statblock-item (label/value), .item-info .details, .more-info-content
// 2) Current: .details-container-equipment with .details-container-content-description-text
//    (Type/Cost/Weight line + description) and table (Name, Cost, Damage, Weight, Properties)
//
// IMPORTANT: do not use named function variables inside page.evaluate —
// esbuild's keepNames injects __name() calls undefined in the browser context.

export async function parseEquipmentPage(page: Page): Promise<EquipmentData> {
  await page
    .waitForSelector(
      ".details-container-equipment, .ddb-statblock-item, .more-info-content",
      { timeout: 15000 }
    )
    .catch(() => {
      throw new Error(`Equipment page did not render at ${page.url()}`);
    });

  return page.evaluate(function (): EquipmentData {
    const name = document.querySelector(".page-title")?.textContent?.trim() ?? "";
    const slug = window.location.pathname.split("/").pop() ?? "";

    const container = document.querySelector(".details-container-equipment");
    if (container) {
      const textBlocks = container.querySelectorAll(".details-container-content-description-text");
      let category = "unknown";
      let cost: string | undefined;
      let damage: string | undefined;
      let weight: string | undefined;
      let properties: string | undefined;
      let armorClass: string | undefined;
      let strength: string | undefined;
      let stealth: string | undefined;
      let description = "";

      const firstBlock = textBlocks[0];
      if (firstBlock) {
        const typeSpan = firstBlock.querySelector(
          "span.details-container-content-description-text-header-margined, span"
        );
        const typeText = typeSpan?.textContent?.trim() ?? "";
        if (typeText) category = typeText.toLowerCase().replace(/\s+/g, "-");
      }

      const table =
        container.querySelector(".table-overflow-wrapper table") ??
        container.querySelector("table");
      if (table) {
        const headers: string[] = [];
        const thEls = table.querySelectorAll("thead th");
        for (let i = 0; i < thEls.length; i++) {
          headers.push((thEls[i].textContent ?? "").trim().toLowerCase());
        }
        const row = table.querySelector("tbody tr");
        if (row) {
          const cells = row.querySelectorAll("td");
          const n = cells.length;
          let costIdx = -1;
          let acIdx = -1;
          let strIdx = -1;
          let steIdx = -1;
          let dmgIdx = -1;
          let propIdx = -1;
          let weightIdx = -1;
          for (let i = 0; i < headers.length; i++) {
            const h = headers[i];
            if (h.includes("cost")) costIdx = i;
            if (h.includes("armor")) acIdx = i;
            if (h.includes("strength")) strIdx = i;
            if (h.includes("stealth")) steIdx = i;
            if (h.includes("damage")) dmgIdx = i;
            if (h.includes("propert")) propIdx = i;
            if (h.includes("weight")) weightIdx = i;
          }
          cost = (costIdx >= 0 && costIdx < n ? cells[costIdx].textContent?.trim() : null) ?? (n > 1 ? cells[1].textContent?.trim() : null) ?? undefined;
          if (acIdx >= 0) {
            armorClass = acIdx < n ? cells[acIdx].textContent?.trim() ?? undefined : undefined;
            strength = strIdx >= 0 && strIdx < n ? cells[strIdx].textContent?.trim() ?? undefined : undefined;
            stealth = steIdx >= 0 && steIdx < n ? cells[steIdx].textContent?.trim() ?? undefined : undefined;
          } else {
            damage = (dmgIdx >= 0 && dmgIdx < n ? cells[dmgIdx].textContent?.trim() : null) ?? (n > 2 ? cells[2].textContent?.trim() : null) ?? undefined;
            properties = (propIdx >= 0 && propIdx < n ? cells[propIdx].textContent?.trim() : null) ?? (n > 4 ? cells[4].textContent?.trim() : null) ?? undefined;
          }
          weight = (weightIdx >= 0 && weightIdx < n ? cells[weightIdx].textContent?.trim() : null) ?? (n > 3 ? cells[3].textContent?.trim() : null) ?? undefined;
        }
      }

      if (textBlocks.length >= 2) {
        const descBlock = textBlocks[1];
        const clone = descBlock.cloneNode(true) as HTMLElement;
        const toRemove = clone.querySelectorAll(".table-overflow-wrapper, table");
        for (let i = 0; i < toRemove.length; i++) toRemove[i].remove();
        description = clone.textContent?.trim() ?? "";
      }

      return {
        name: name || slug,
        slug,
        category,
        cost,
        damage,
        weight,
        properties,
        armorClass,
        strength,
        stealth,
        description,
      };
    }

    const subtitle =
      document.querySelector(".item-info .details")?.textContent?.trim() ??
      document.querySelector(".equipment-type")?.textContent?.trim() ??
      "";
    const category = subtitle.toLowerCase().replace(/\s+/g, "-") || "unknown";

    const stats: Record<string, string> = {};
    const statItems = document.querySelectorAll(".ddb-statblock-item");
    for (let i = 0; i < statItems.length; i++) {
      const item = statItems[i];
      const label =
        item.querySelector(".ddb-statblock-item-label")?.textContent?.trim().toLowerCase() ?? "";
      const value =
        item.querySelector(".ddb-statblock-item-value")?.textContent?.trim() ?? "";
      if (label) stats[label] = value;
    }

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
      armorClass: undefined,
      strength: undefined,
      stealth: undefined,
      description,
    };
  });
}
