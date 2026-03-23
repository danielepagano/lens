import type { Page } from "playwright";
import type { FeatureParentKind } from "../types.js";

const BASE_URL = "https://www.dndbeyond.com";

export function featureIndexUrl(kind: FeatureParentKind): string {
  return kind === "class" ? `${BASE_URL}/classes` : `${BASE_URL}/species`;
}

export async function parseFeatureIndexPage(
  page: Page,
  kind: FeatureParentKind,
  groupLabel: string
): Promise<string[]> {
  await page
    .waitForSelector(".j-collapsible, .ddb-collapsible__label", { timeout: 20000 })
    .catch(() => {
      throw new Error(`Feature index page did not render at ${page.url()}`);
    });

  const urls = await page.evaluate(
    ({ featureKind, label }): string[] => {
      const wanted = label.trim().toLowerCase();
      const pathPrefix = featureKind === "class" ? "/classes/" : "/species/";
      const items = new Set<string>();

      document.querySelectorAll<HTMLElement>(".j-collapsible").forEach((group) => {
        const text =
          group.querySelector<HTMLElement>(".ddb-collapsible__label")?.textContent?.trim() ?? "";
        if (text.toLowerCase() !== wanted) return;
        group
          .querySelectorAll<HTMLElement>(".j-collapsible__item")
          .forEach((card) => {
            const legacyBadge = card.querySelector<HTMLElement>("#legacy-badge, .badge-label");
            const legacyText = legacyBadge?.textContent?.trim().toLowerCase() ?? "";
            if (legacyText === "legacy") return;

            const anchor = card.querySelector<HTMLAnchorElement>("a.listing-card__link[href]");
            if (!anchor) return;
            const href = anchor.getAttribute("href") ?? "";
            if (!href.startsWith(pathPrefix)) return;
            const url = href.startsWith("http") ? href : `${"https://www.dndbeyond.com"}${href}`;
            items.add(url);
          });
      });

      return Array.from(items);
    },
    { featureKind: kind, label: groupLabel }
  );

  if (urls.length === 0) {
    throw new Error(
      `No ${kind} detail URLs found for group "${groupLabel}" at ${page.url()}`
    );
  }

  return urls;
}
