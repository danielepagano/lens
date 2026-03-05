import type { Page } from "playwright";
import type { ListItem } from "../types.js";

// DnD Beyond list page URL patterns:
//   /spells?filter-source={id}&page=N
//   /monsters?filter-source={id}&page=N
//   /magic-items?filter-source={id}&page=N
//   /equipment?filter-source={id}&page=N
//
// Confirmed selectors (verified 2026-03-04 against live DOM):
//   List container:    .listing-body [data-slug]  (row = div.info direct child of ul.listing)
//   Name link path:    #content > section > div > .listing-body > ul > div > .row.XXX-name > span.name > a
//   Row link:          span.name a  or  a.link[href^="/"]  (detail link; first a[href] is often image)
//   Pagination next:   li.b-pagination-item-next containing a[href] when next page exists
//   Environment tags:  span.tag.environment-tag  (monsters only, on list rows)

const BASE_URL = "https://www.dndbeyond.com";

export type ContentType = "spells" | "monsters" | "magic-items" | "equipment";

function listPath(type: ContentType): string {
  return `/${type}`;
}

/** Parse list items from the currently loaded list page (no navigation). */
export async function parseListPage(page: Page, type: ContentType): Promise<ListItem[]> {
  await page
    .waitForSelector(".listing-body [data-slug], .listing-empty", { timeout: 20000 })
    .catch(() => {
      throw new Error(`List page did not render at ${page.url()}`);
    });

  return page.evaluate(
    (contentType: string): ListItem[] => {
      const results: ListItem[] = [];
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
        const item: ListItem = { slug, url: `https://www.dndbeyond.com${href}`, name };
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
    const url = `${BASE_URL}${listPath(type)}?filter-source=${filterId}&page=${pageNum}`;
    if (verbose) console.log(`  [list] ${url}`);

    await page.goto(url, { waitUntil: "networkidle" });

    await page
      .waitForSelector(".listing-body [data-slug], .listing-empty", { timeout: 15000 })
      .catch(() => {
        throw new Error(`List page did not render for ${type} page ${pageNum}`);
      });

    const items = await page.evaluate(
      (contentType: string): ListItem[] => {
        const results: ListItem[] = [];

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
            url: `https://www.dndbeyond.com${href}`,
            name,
          };

          // Habitats — only present on monster rows
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
