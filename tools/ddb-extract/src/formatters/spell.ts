import type { SpellData } from "../types.js";
import { slugifyKey, toTagSlug, levelLabel, titleCase, wrapKbBlock } from "./kb.js";

export function formatSpell(data: SpellData, source: string): string {
  const key = slugifyKey(data.slug);
  const id = `spell.${key}`;

  const tags: string[] = [
    `source:${source}`,
    `level:${data.level}`,
    `school:${toTagSlug(data.school)}`,
  ];
  if (data.isRitual) tags.push("ritual");

  const schoolTitle = titleCase(data.school);
  const levelStr = data.level === 0 ? "Cantrip" : `${levelLabel(data.level)} ${schoolTitle}`;
  const headline = `**${data.name}** · ${levelStr}`;

  let body =
    `${headline}\n\n` +
    `**Casting Time**: ${data.castingTime}\n` +
    `**Range**: ${data.range}\n` +
    `**Components**: ${data.components}\n` +
    `**Duration**: ${data.duration}\n\n` +
    data.description;

  if (data.higherLevel) {
    body += `\n\n**Using a Higher-Level Spell Slot.** ${data.higherLevel}`;
  }

  return wrapKbBlock(id, tags, body);
}
