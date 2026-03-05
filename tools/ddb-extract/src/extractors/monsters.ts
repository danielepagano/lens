import type { Page } from "playwright";
import type { MonsterData, ListItem } from "../types.js";
import { ListExtractor } from "./base.js";
import { parseMonsterPage } from "../parsers/monster-page.js";
import { formatMonster } from "../formatters/monster.js";

export class MonsterExtractor extends ListExtractor<MonsterData> {
  readonly type = "monsters" as const;

  fetchDetail(page: Page, item: ListItem): Promise<MonsterData> {
    return parseMonsterPage(page, item.habitats ?? []);
  }

  format(data: MonsterData, source: string): string {
    return formatMonster(data, source);
  }
}
