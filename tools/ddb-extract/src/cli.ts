#!/usr/bin/env tsx
import { Command } from "commander";
import { existsSync } from "fs";
import { resolve } from "path";
import { connectCDP, getPage, sleep } from "./browser.js";
import { loadSources, resolveSource, writeFilterId, mergeDiscoveredSources } from "./sources.js";
import { discoverSources } from "./parsers/source-filter.js";
import {
  createOutputFile,
  scanDoneSet,
  appendBlock,
  appendFailure,
} from "./output.js";
import { SpellExtractor } from "./extractors/spells.js";
import { MonsterExtractor } from "./extractors/monsters.js";
import { ItemExtractor } from "./extractors/items.js";
import { EquipmentExtractor } from "./extractors/equipment.js";
import type { ListExtractor } from "./extractors/base.js";
import {
  extractListItems,
  parseListPage,
  type ContentType,
} from "./parsers/list-page.js";
import { parseSpellPage } from "./parsers/spell-page.js";
import { parseEquipmentPage } from "./parsers/equipment-page.js";
import { parseItemPage } from "./parsers/item-page.js";
import { parseMonsterPage } from "./parsers/monster-page.js";

const program = new Command();

program
  .name("ddb")
  .description("D&D Beyond content extractor for Lens KB")
  .option("--cdp-url <url>", "Chrome DevTools Protocol URL", "http://localhost:9222")
  .option("--delay <ms>", "Delay between page loads (ms)", "800")
  .option("--dry-run", "Enumerate without writing", false)
  .option("--verbose", "Log each page load", false)
  .option("--strict", "Abort on first parse failure", false);

// ── check ────────────────────────────────────────────────────────────────────
program
  .command("check")
  .description("Verify CDP connection and DnD Beyond authentication")
  .action(async () => {
    const opts = program.opts();
    console.log(`Connecting to Chrome at ${opts.cdpUrl}...`);
    const browser = await connectCDP(opts.cdpUrl);
    const page = getPage(browser);
    console.log("Connected. Navigating to D&D Beyond account page...");
    await page.goto("https://www.dndbeyond.com/account", {
      waitUntil: "networkidle",
    });
    const title = await page.title();
    const url = page.url();
    if (url.includes("/sign-in") || url.includes("/login")) {
      console.error("Not authenticated: redirected to sign-in page.");
      process.exit(1);
    }
    console.log(`OK. Page title: "${title}"`);
    console.log("D&D Beyond session is active.");
    await browser.close();
  });

// ── parse ─────────────────────────────────────────────────────────────────────
// For testing: load a URL, run a parser, pretty-print JSON. Use spell URL + spell
// parser (works); spell URL + equipment parser (fails with selector error).
program
  .command("parse")
  .description(
    "Load a URL, run a parser (spell|equipment|item|monster|list), print JSON. For testing."
  )
  .requiredOption("--parser <name>", "Parser: spell | equipment | item | monster | list")
  .requiredOption("--url <url>", "Page URL to load (e.g. a D&D Beyond spell or list page)")
  .action(async (cmdOpts: { parser: string; url: string }) => {
    const opts = program.opts();
    const parserName = cmdOpts.parser.toLowerCase();
    const url = cmdOpts.url;

    const browser = await connectCDP(opts.cdpUrl as string);
    const page = getPage(browser);

    const isListParser = parserName === "list";
    const waitUntil = cmdOpts.debug || isListParser ? "domcontentloaded" : "networkidle";
    const timeout = cmdOpts.debug || isListParser ? 60000 : 30000;
    try {
      await page.goto(url, { waitUntil, timeout });
    } catch (err) {
      console.error("Failed to load URL:", err instanceof Error ? err.message : String(err));
      await browser.close();
      process.exit(1);
    }

    try {
      let result: unknown;
      switch (parserName) {
        case "spell":
          result = await parseSpellPage(page);
          break;
        case "equipment":
          result = await parseEquipmentPage(page);
          break;
        case "item":
          result = await parseItemPage(page);
          break;
        case "monster":
          result = await parseMonsterPage(page, []);
          break;
        case "list": {
          const pathname = new URL(url).pathname;
          const typeMatch = pathname.match(/^\/(spells|monsters|magic-items|equipment)/);
          const type = (typeMatch?.[1] ?? "spells") as ContentType;
          result = await parseListPage(page, type);
          break;
        }
        default:
          console.error(
            `Unknown parser "${parserName}". Use: spell | equipment | item | monster | list`
          );
          await browser.close();
          process.exit(1);
      }
      console.log(JSON.stringify(result, null, 2));
    } catch (err) {
      console.error("Parse error:", err instanceof Error ? err.message : String(err));
      await browser.close();
      process.exit(1);
    }

    await browser.close();
  });

// ── sources ──────────────────────────────────────────────────────────────────
program
  .command("sources")
  .description("List all known sources")
  .action(() => {
    const sources = loadSources();
    console.log("\nKnown sources:\n");
    for (const [slug, entry] of Object.entries(sources)) {
      const id = entry.filterId !== null ? `id=${entry.filterId}` : "no filter ID (run discover)";
      console.log(`  ${slug.padEnd(20)} ${entry.name}  [${id}]`);
      console.log(`  ${"".padEnd(20)} types: ${entry.types.join(", ")}`);
    }
  });

// ── discover ─────────────────────────────────────────────────────────────────
program
  .command("discover <slug>")
  .description("Find and record the filter ID for a source")
  .action(async (slug: string) => {
    const opts = program.opts();
    const sources = loadSources();
    if (!sources[slug]) {
      console.error(`Unknown source slug "${slug}". Add it to config/sources.json first.`);
      process.exit(1);
    }

    const browser = await connectCDP(opts.cdpUrl);
    const page = getPage(browser);

    // Navigate to the source page to confirm it exists
    const sourceUrl = `https://www.dndbeyond.com/sources/dnd/${slug}`;
    console.log(`Navigating to ${sourceUrl}...`);
    await page.goto(sourceUrl, { waitUntil: "networkidle" });

    // Navigate to /spells with source filter open to find the ID
    // Strategy: navigate to /spells, open the source filter, read option values
    console.log("Opening spell list to discover source filter ID...");
    await page.goto("https://www.dndbeyond.com/spells", { waitUntil: "networkidle" });

    // Try to extract filter options — DnD Beyond renders source filter as a select or
    // a list of checkboxes with data attributes
    const filterId = await page.evaluate((sourceName: string) => {
      // Look for option elements with matching text
      const options = document.querySelectorAll<HTMLOptionElement>(
        "select option, .filter-option, [data-source-id]"
      );
      for (const opt of options) {
        const text = opt.textContent?.trim() ?? "";
        const val = opt.getAttribute("value") ?? opt.getAttribute("data-source-id") ?? "";
        if (text.toLowerCase().includes(sourceName.toLowerCase()) && val.match(/^\d+$/)) {
          return parseInt(val);
        }
      }
      return null;
    }, sources[slug].name);

    if (filterId !== null) {
      writeFilterId(slug, filterId);
      console.log(`Found filter ID ${filterId} for "${slug}". Saved to sources.json.`);
    } else {
      console.log(
        `Could not automatically determine filter ID for "${slug}".\n` +
          `Please manually inspect the source filter on https://www.dndbeyond.com/spells\n` +
          `and add the numeric ID to config/sources.json.`
      );
    }

    await browser.close();
  });

// ── discover-all ─────────────────────────────────────────────────────────────
program
  .command("discover-all")
  .description("Scrape all source filter options from every list page and update sources.json")
  .action(async () => {
    const opts = program.opts();
    const verbose = opts.verbose as boolean;

    const browser = await connectCDP(opts.cdpUrl as string);
    const page = getPage(browser);

    console.log("Discovering sources from D&D Beyond...");
    const discovered = await discoverSources(page, verbose);
    await browser.close();

    if (discovered.length === 0) {
      console.error(
        "No sources found. The selector may have changed — check select#filter-source\n" +
          "in src/parsers/source-filter.ts against the live DOM on dndbeyond.com/spells."
      );
      process.exit(1);
    }

    const { added } = mergeDiscoveredSources(discovered);

    console.log(`Found ${discovered.length} sources. Added ${added} new entries to sources.json.`);
    if (added > 0) {
      console.log("New entries have types: [] — set types manually before using --type all.");
    }
    console.log("Run `ddb sources` to review.");
  });

// ── extract ──────────────────────────────────────────────────────────────────
program
  .command("extract")
  .description("Extract content from D&D Beyond into KB Markdown files")
  .requiredOption("--type <type>", "Content type: spells|monsters|items|equipment|all")
  .requiredOption("--source <slug>", "Source slug from sources.json")
  .requiredOption("--out <dir>", "Output directory")
  .option("--limit <n>", "Limit to N items (for testing)")
  .action(async (cmdOpts: { type: string; source: string; out: string; limit?: string }) => {
    const opts = program.opts();
    const delayMs = parseInt(opts.delay as string) || 800;
    const dryRun = opts.dryRun as boolean;
    const verbose = opts.verbose as boolean;
    const strict = opts.strict as boolean;
    const limit = cmdOpts.limit ? parseInt(cmdOpts.limit) : undefined;

    const sourceEntry = resolveSource(cmdOpts.source);

    const extractors: ListExtractor<unknown>[] = [];
    const requestedType = cmdOpts.type.toLowerCase();

    const typeMap: Record<string, ListExtractor<unknown>> = {
      spells: new SpellExtractor(),
      monsters: new MonsterExtractor(),
      items: new ItemExtractor(),
      equipment: new EquipmentExtractor(),
    };

    if (requestedType === "all") {
      for (const t of sourceEntry.types) {
        const ext = typeMap[t];
        if (ext) extractors.push(ext);
        else console.warn(`  Warning: no extractor for type "${t}"`);
      }
    } else {
      const ext = typeMap[requestedType];
      if (!ext) {
        console.error(
          `Unknown type "${requestedType}". Valid types: spells, monsters, items, equipment, all`
        );
        process.exit(1);
      }
      extractors.push(ext);
    }

    const browser = await connectCDP(opts.cdpUrl as string);
    const page = getPage(browser);

    let totalExtracted = 0;
    let totalSkipped = 0;
    let totalFailed = 0;

    for (const extractor of extractors) {
      const typeLabel = extractor.type;
      const outputPath = resolve(cmdOpts.out, `${cmdOpts.source}-${typeLabel}.md`);

      console.log(`\n=== ${cmdOpts.source} / ${typeLabel} ===`);
      console.log(`Output: ${outputPath}`);

      // Enumerate once — reused for both the file header count and the extraction run
      console.log("  Enumerating list...");
      const allItems = await extractListItems(page, extractor.type, sourceEntry.filterId!, verbose);

      // Set up output file or scan existing
      let doneSet: Set<string>;
      if (existsSync(outputPath)) {
        doneSet = scanDoneSet(outputPath);
        console.log(`  Resuming: ${doneSet.size} items already done`);
      } else {
        doneSet = new Set();
        if (!dryRun) {
          createOutputFile(outputPath, cmdOpts.source, typeLabel, allItems.length);
        }
      }

      const result = await extractor.run(page, sourceEntry.filterId!, {
        delayMs,
        dryRun,
        verbose,
        strict,
        outputPath,
        source: cmdOpts.source,
        doneSet,
        limit,
        items: allItems,
      });

      totalExtracted += result.extracted;
      totalSkipped += result.skipped;
      totalFailed += result.failed;

      console.log(
        `  Done: ${result.extracted} extracted, ${result.skipped} skipped, ${result.failed} failed`
      );
    }

    console.log(
      `\nTotal: ${totalExtracted} extracted, ${totalSkipped} skipped, ${totalFailed} failed`
    );

    await browser.close();
  });

program.parseAsync(process.argv).catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
});
