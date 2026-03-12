import type { Page } from "playwright";
import type { ListItem } from "../types.js";

// DnD Beyond list page URL patterns:
//   /spells?filter-source={id}&filter-partnered-content=t&page=N
//   /monsters?filter-source={id}&filter-partnered-content=t&page=N
//   /magic-items?filter-source={id}&filter-partnered-content=t&page=N
//   /equipment?filter-source={id}&filter-partnered-content=t&page=N
//
// Confirmed selectors (verified 2026-03-04 against live DOM):
//   Spells/monsters/items: .listing-body [data-slug]  (row = div.info), span.name a or a.link
//   Equipment:            .listing-body .list-row-equipment  (no data-slug; slug from a.link href)
//   Pagination next:      li.b-pagination-item-next containing a[href] when next page exists
//   Environment tags:     span.tag.environment-tag  (monsters only, on list rows)

const BASE_URL = "https://www.dndbeyond.com";

export type ContentType = "spells" | "monsters" | "magic-items" | "equipment";

function listPath(type: ContentType): string {
  return `/${type}`;
}

const LIST_READY_SELECTOR =
  ".listing-body [data-slug], .listing-body .list-row-equipment, .listing-empty";

/** Parse list items from the currently loaded list page (no navigation). */
export async function parseListPage(page: Page, type: ContentType): Promise<ListItem[]> {
  await page
    .waitForSelector(LIST_READY_SELECTOR, { timeout: 20000 })
    .catch(() => {
      throw new Error(`List page did not render at ${page.url()}`);
    });

  return page.evaluate(
    (contentType: string): ListItem[] => {
      const results: ListItem[] = [];
      const base = "https://www.dndbeyond.com";

      if (contentType === "equipment") {
        const rows = document.querySelectorAll<HTMLElement>(".listing-body .list-row-equipment");
        rows.forEach((row) => {
          const anchor = row.querySelector<HTMLAnchorElement>('a.link[href^="/equipment/"]');
          if (!anchor) return;
          const href = anchor.getAttribute("href") ?? "";
          const slug = href.replace(/^\/equipment\/?/, "").split("?")[0].trim() || "";
          if (!slug) return;
          const name = anchor.textContent?.trim() ?? slug;
          results.push({ slug, url: `${base}${href}`, name });
        });
        return results;
      }

      const rows = document.querySelectorAll<HTMLElement>(".listing-body [data-slug]");
      rows.forEach((row) => {
        const slug = row.getAttribute("data-slug") ?? "";
        if (!slug) return;
        const anchor =
          row.querySelector<HTMLAnchorElement>("span.name a") ??
          row.querySelector<HTMLAnchorElement>('a.link[href^="/"]');
        if (!anchor) return;
        const href = anchor.getAttribute("href") ?? "";
        const name = anchor.textContent?.trim() ?? slug;
        const item: ListItem = { slug, url: `${base}${href}`, name };
        if (contentType === "monsters") {
          const habitatTags = row.querySelectorAll<HTMLElement>("span.tag.environment-tag");
          if (habitatTags.length > 0) {
            item.habitats = Array.from(habitatTags).map(
              (el) => el.textContent?.trim() ?? ""
            );
          }
        }
        results.push(item);
      });
      return results;
    },
    type as string
  );
}

export async function extractListItems(
  page: Page,
  type: ContentType,
  filterId: number,
  verbose: boolean
): Promise<ListItem[]> {
  const allItems: ListItem[] = [];
  let pageNum = 1;

  while (true) {
    const url = `${BASE_URL}${listPath(type)}?filter-source=${filterId}&filter-partnered-content=t&page=${pageNum}`;
    if (verbose) console.log(`  [list] ${url}`);

    await page.goto(url, { waitUntil: "networkidle" });

    await page
      .waitForSelector(LIST_READY_SELECTOR, { timeout: 15000 })
      .catch(() => {
        throw new Error(`List page did not render for ${type} page ${pageNum}`);
      });

    const items = await page.evaluate(
      (contentType: string): ListItem[] => {
        const results: ListItem[] = [];
        const base = "https://www.dndbeyond.com";

        if (contentType === "equipment") {
          const rows = document.querySelectorAll<HTMLElement>(".listing-body .list-row-equipment");
          rows.forEach((row) => {
            const anchor = row.querySelector<HTMLAnchorElement>('a.link[href^="/equipment/"]');
            if (!anchor) return;
            const href = anchor.getAttribute("href") ?? "";
            const slug = href.replace(/^\/equipment\/?/, "").split("?")[0].trim() || "";
            if (!slug) return;
            const name = anchor.textContent?.trim() ?? slug;
            results.push({ slug, url: `${base}${href}`, name });
          });
          return results;
        }

        const rows = document.querySelectorAll<HTMLElement>(".listing-body [data-slug]");
        rows.forEach((row) => {
          const slug = row.getAttribute("data-slug") ?? "";
          if (!slug) return;
          const anchor =
            row.querySelector<HTMLAnchorElement>("span.name a") ??
            row.querySelector<HTMLAnchorElement>('a.link[href^="/"]');
          if (!anchor) return;
          const href = anchor.getAttribute("href") ?? "";
          const name = anchor.textContent?.trim() ?? slug;

          const item: ListItem = {
            slug,
            url: `${base}${href}`,
            name,
          };

          if (contentType === "monsters") {
            const habitatTags = row.querySelectorAll<HTMLElement>(
              "span.tag.environment-tag"
            );
            if (habitatTags.length > 0) {
              item.habitats = Array.from(habitatTags).map(
                (el) => el.textContent?.trim() ?? ""
              );
            }
          }

          results.push(item);
        });

        return results;
      },
      type as string
    );

    allItems.push(...items);

    if (items.length === 0) break;

    // Check for next page: the Next button is <li class="b-pagination-item-next">
    // containing an <a href="..."> when there is a next page.
    const hasNext = await page
      .evaluate(() => {
        const nextLi = document.querySelector("li.b-pagination-item-next");
        return !!nextLi?.querySelector("a[href]");
      })
      .catch(() => false);

    if (!hasNext) break;
    pageNum++;
  }

  // Deduplicate by slug (some items appear in multiple sources)
  const seen = new Set<string>();
  return allItems.filter((item) => {
    if (seen.has(item.slug)) return false;
    seen.add(item.slug);
    return true;
  });
}
