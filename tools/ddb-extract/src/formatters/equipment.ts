import type { EquipmentData } from "../types.js";
import { slugifyKey, toTagSlug, wrapKbBlock } from "./kb.js";

export function formatEquipment(data: EquipmentData, source: string): string {
  const key = slugifyKey(data.slug);
  const id = `equipment.${key}`;

  const tags: string[] = [
    // `source:${source}`,
    `category:${toTagSlug(data.category)}`,
  ];

  const catTitle =
    data.category.charAt(0).toUpperCase() + data.category.slice(1).replace(/-/g, " ");

  let headline = `**${data.name}** · ${catTitle}`;

  const stats: string[] = [];
  if (data.cost) stats.push(`**Cost** ${data.cost}`);
  if (data.armorClass) stats.push(`**Armor Class** ${data.armorClass}`);
  if (data.damage) stats.push(`**Damage** ${data.damage}`);
  if (data.strength) stats.push(`**Strength** ${data.strength}`);
  if (data.stealth) stats.push(`**Stealth** ${data.stealth}`);
  if (data.weight) stats.push(`**Weight** ${data.weight}`);

  let body = headline;
  if (stats.length > 0) {
    body += `\n\n${stats.join(" · ")}`;
  }
  if (data.properties) {
    body += `\n**Properties** ${data.properties}`;
  }
  if (data.description) {
    body += `\n\n${data.description}`;
  }

  return wrapKbBlock(id, tags, body);
}
