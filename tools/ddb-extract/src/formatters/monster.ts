import type { MonsterData } from "../types.js";
import { slugifyKey, toTagSlug, encodeCR, titleCase, wrapKbBlock } from "./kb.js";

function abilMod(score: number): string {
  const mod = Math.floor((score - 10) / 2);
  return mod >= 0 ? `+${mod}` : `${mod}`;
}

function abilCell(score: number): string {
  return `${score} (${abilMod(score)})`;
}

export function formatMonster(data: MonsterData, source: string): string {
  const key = slugifyKey(data.slug);
  const id = `stat.${key}`;

  const tags: string[] = [
    `source:${source}`,
    `cr:${encodeCR(data.cr)}`,
    `type:${toTagSlug(data.type)}`,
    `size:${toTagSlug(data.size)}`,
    ...data.habitats.map((h) => `habitat:${toTagSlug(h)}`),
  ];

  const sizeTitle = titleCase(data.size);
  const typeTitle = titleCase(data.type);

  let body =
    `**${data.name}** · ${sizeTitle} ${typeTitle}, ${data.alignment}\n\n` +
    `**AC** ${data.ac} · **HP** ${data.hp} · **Speed** ${data.speed}\n\n` +
    `| STR | DEX | CON | INT | WIS | CHA |\n` +
    `|-----|-----|-----|-----|-----|-----|\n` +
    `| ${abilCell(data.abilities.str)} | ${abilCell(data.abilities.dex)} | ${abilCell(data.abilities.con)} | ${abilCell(data.abilities.int)} | ${abilCell(data.abilities.wis)} | ${abilCell(data.abilities.cha)} |\n`;

  if (data.skills) body += `\n**Skills** ${data.skills}`;
  if (data.senses) body += `\n**Senses** ${data.senses}`;
  if (data.languages) body += `\n**Languages** ${data.languages}`;
  body += `\n**CR** ${data.cr}`;

  if (data.traits) {
    body += `\n\n${data.traits}`;
  }

  if (data.actions) {
    body += `\n\n---\n**Actions**\n\n${data.actions}`;
  }

  if (data.reactions) {
    body += `\n\n---\n**Reactions**\n\n${data.reactions}`;
  }

  if (data.legendaryActions) {
    body += `\n\n---\n**Legendary Actions**\n\n${data.legendaryActions}`;
  }

  if (data.description) {
    body += `\n\n---\n**Description**\n\n${data.description}`;
  }

  return wrapKbBlock(id, tags, body);
}
