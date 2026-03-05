import type { Page } from "playwright";
import type { ListItem } from "../types.js";
import { appendBlock, appendFailure } from "../output.js";
import { sleep } from "../browser.js";
import { extractListItems } from "../parsers/list-page.js";

export interface ExtractorOptions {
  delayMs: number;
  dryRun: boolean;
  verbose: boolean;
  strict: boolean;
  outputPath: string;
  source: string;
  doneSet: Set<string>;
  limit?: number;
  /** Pre-enumerated items — if provided, skips the internal extractListItems call. */
  items?: ListItem[];
}

export interface ExtractorResult {
  extracted: number;
  skipped: number;
  failed: number;
}

export abstract class ListExtractor<T> {
  abstract readonly type: "spells" | "monsters" | "magic-items" | "equipment";

  abstract fetchDetail(page: Page, item: ListItem): Promise<T>;
  abstract format(data: T, source: string): string;

  /** Extract the KB id from formatted block (for done-set cross-check) */
  protected idFromBlock(block: string): string | undefined {
    const m = block.match(/^id:\s*(.+)$/m);
    return m?.[1]?.trim();
  }

  async run(
    page: Page,
    filterId: number,
    opts: ExtractorOptions
  ): Promise<ExtractorResult> {
    const { delayMs, dryRun, verbose, strict, outputPath, source, doneSet, limit } = opts;

    let allItems = opts.items;
    if (!allItems) {
      if (verbose) console.log(`\n[enumerate] ${this.type} filterId=${filterId}`);
      allItems = await extractListItems(page, this.type, filterId, verbose);
    }

    const workQueue = allItems.filter((item) => {
      // Check against done set using the id that would be generated
      // We check slug-based done-set membership by regenerating expected id format
      const slugKey = item.slug.replace(/^\d+-/, "");
      const prefixes = ["spell", "stat", "item", "equipment"];
      for (const p of prefixes) {
        if (doneSet.has(`${p}.${slugKey}`) || doneSet.has(`${p}.${item.slug}`)) {
          return false;
        }
      }
      return true;
    });

    const skipped = allItems.length - workQueue.length;
    const total = limit ? Math.min(workQueue.length, limit) : workQueue.length;

    console.log(
      `  ${allItems.length} total, ${skipped} already done, ${total} to extract`
    );

    if (dryRun) {
      workQueue.slice(0, total).forEach((item) =>
        console.log(`  [dry-run] ${item.slug}`)
      );
      return { extracted: 0, skipped, failed: 0 };
    }

    let extracted = 0;
    let failed = 0;

    for (const item of workQueue.slice(0, total)) {
      try {
        if (verbose) console.log(`  [fetch] ${item.url}`);
        await page.goto(item.url, { waitUntil: "networkidle", timeout: 30000 });
        const data = await this.fetchDetail(page, item);
        // Inject source URL annotation inside the kb block (before closing fence)
        // so it is stored with the object. Format: [ddb-source]: URL
        // This is a markdown reference definition — renders as nothing.
        const raw = this.format(data, source);
        const block = raw.endsWith("\n```")
          ? raw.slice(0, -3) + `\n[source: ${item.url}]: #\n\`\`\``
          : raw;
        appendBlock(outputPath, block);
        extracted++;
        process.stdout.write(
          `\r  extracted: ${extracted} / ${total}  failed: ${failed}    `
        );
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        console.error(`\n  [fail] ${item.slug}: ${reason}`);
        appendFailure(outputPath, item.slug, reason);
        failed++;
        if (strict) {
          throw new Error(`Strict mode: aborting on first failure (${item.slug})`);
        }
      }
      await sleep(delayMs);
    }

    process.stdout.write("\n");
    return { extracted, skipped, failed };
  }
}
