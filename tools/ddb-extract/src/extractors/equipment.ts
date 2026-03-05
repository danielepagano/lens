import type { Page } from "playwright";
import type { EquipmentData, ListItem } from "../types.js";
import { ListExtractor } from "./base.js";
import { parseEquipmentPage } from "../parsers/equipment-page.js";
import { formatEquipment } from "../formatters/equipment.js";

export class EquipmentExtractor extends ListExtractor<EquipmentData> {
  readonly type = "equipment" as const;

  fetchDetail(page: Page, _item: ListItem): Promise<EquipmentData> {
    return parseEquipmentPage(page);
  }

  format(data: EquipmentData, source: string): string {
    return formatEquipment(data, source);
  }
}
