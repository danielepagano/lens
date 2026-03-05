import type { Page } from "playwright";
import type { SpellData, ListItem } from "../types.js";
import { ListExtractor } from "./base.js";
import { parseSpellPage } from "../parsers/spell-page.js";
import { formatSpell } from "../formatters/spell.js";

export class SpellExtractor extends ListExtractor<SpellData> {
  readonly type = "spells" as const;

  fetchDetail(page: Page, _item: ListItem): Promise<SpellData> {
    return parseSpellPage(page);
  }

  format(data: SpellData, source: string): string {
    return formatSpell(data, source);
  }
}
