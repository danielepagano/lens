import type { Page } from "playwright";
import type { ItemData, ListItem } from "../types.js";
import { ListExtractor } from "./base.js";
import { parseItemPage } from "../parsers/item-page.js";
import { formatItem } from "../formatters/item.js";

export class ItemExtractor extends ListExtractor<ItemData> {
  readonly type = "magic-items" as const;

  fetchDetail(page: Page, _item: ListItem): Promise<ItemData> {
    return parseItemPage(page);
  }

  format(data: ItemData, source: string): string {
    return formatItem(data, source);
  }
}
