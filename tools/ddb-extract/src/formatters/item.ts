import type { ItemData } from "../types.js";
import { slugifyKey, toTagSlug, wrapKbBlock } from "./kb.js";

export function formatItem(data: ItemData, source: string): string {
  const key = slugifyKey(data.slug);
  const id = `item.${key}`;

  const tags: string[] = [
    // `source:${source}`,
    `rarity:${toTagSlug(data.rarity)}`,
    `type:${toTagSlug(data.itemType)}`,
  ];
  if (data.requiresAttunement) tags.push("requires-attunement");

  const rarityTitle =
    data.rarity.charAt(0).toUpperCase() + data.rarity.slice(1).replace(/-/g, " ");
  const typeTitle =
    data.itemType.charAt(0).toUpperCase() + data.itemType.slice(1).replace(/-/g, " ");
  const attunement = data.requiresAttunement ? ", Requires Attunement" : "";
  const subtitle = `${typeTitle} (${rarityTitle}${attunement})`;

  const body = `**${data.name}** · ${subtitle}\n\n${data.description}`;

  return wrapKbBlock(id, tags, body);
}
