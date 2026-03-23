import type { Page } from "playwright";
import { appendBlock, appendFailure } from "../output.js";
import { sleep } from "../browser.js";
import type { FeatureParentKind } from "../types.js";
import { parseFeatureIndexPage, featureIndexUrl } from "../parsers/feature-index.js";
import { parseFeaturePage } from "../parsers/feature-page.js";
import { formatFeature } from "../formatters/feature.js";
import { createOutputFile, scanDoneSet } from "../output.js";
import { existsSync } from "fs";

export interface FeatureExtractOptions {
  kind: FeatureParentKind;
  url?: string;
  group?: string;
  delayMs: number;
  dryRun: boolean;
  verbose: boolean;
  strict: boolean;
  outputPath: string;
  source: string;
  doneSet: Set<string>;
  limit?: number;
}

export interface FeatureExtractResult {
  extracted: number;
  skipped: number;
  failed: number;
}

function idFromBlock(block: string): string | undefined {
  const match = block.match(/^id:\s*(.+)$/m);
  return match?.[1]?.trim();
}

export async function extractFeatures(
  page: Page,
  opts: FeatureExtractOptions
): Promise<FeatureExtractResult> {
  const { kind, url, group, delayMs, dryRun, verbose, strict, outputPath, doneSet, limit } = opts;
  const indexUrl = featureIndexUrl(kind);
  let detailUrls: string[] = [];

  if (url) {
    detailUrls = [url];
  } else if (group) {
    if (verbose) console.log(`  [index] ${indexUrl}`);
    await page.goto(indexUrl, { waitUntil: "networkidle", timeout: 30000 });
    detailUrls = await parseFeatureIndexPage(page, kind, group);
  } else {
    throw new Error(`Missing target for ${kind}-features extraction: use --url or --group`);
  }

  const totalPages = limit ? Math.min(detailUrls.length, limit) : detailUrls.length;
  const queue = detailUrls.slice(0, totalPages);
  let extracted = 0;
  let skipped = 0;
  let failed = 0;
  const doneSetsByPath = new Map<string, Set<string>>();
  doneSetsByPath.set(outputPath, doneSet);

  const targetPathForFeature = (subclassContentSlug?: string): string => {
    if (kind !== "class" || !subclassContentSlug) return outputPath;
    return outputPath.replace(/\.md$/i, `-${subclassContentSlug}.md`);
  };

  const ensureDoneSet = (path: string): Set<string> => {
    const existing = doneSetsByPath.get(path);
    if (existing) return existing;
    const set = existsSync(path) ? scanDoneSet(path) : new Set<string>();
    doneSetsByPath.set(path, set);
    if (!dryRun && !existsSync(path)) {
      createOutputFile(path, opts.source, "class-features", 0);
    }
    return set;
  };

  for (const detailUrl of queue) {
    try {
      if (verbose) console.log(`  [fetch] ${detailUrl}`);
      await page.goto(detailUrl, { waitUntil: "networkidle", timeout: 30000 });
      const features = await parseFeaturePage(page, kind);

      for (const feature of features) {
        const block = formatFeature(feature);
        const id = idFromBlock(block);
        if (!id) {
          failed += 1;
          appendFailure(outputPath, feature.featureSlug, "Formatter did not produce an id");
          if (strict) throw new Error("Strict mode: formatter produced block without id");
          continue;
        }
        const featureOutputPath = targetPathForFeature(feature.subclassContentSlug);
        const featureDoneSet = ensureDoneSet(featureOutputPath);
        if (featureDoneSet.has(id)) {
          skipped += 1;
          continue;
        }
        if (dryRun) {
          console.log(`  [dry-run] ${id} -> ${featureOutputPath}`);
          continue;
        }
        appendBlock(featureOutputPath, block);
        featureDoneSet.add(id);
        extracted += 1;
      }
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      appendFailure(outputPath, detailUrl, reason);
      failed += 1;
      if (strict) {
        throw new Error(`Strict mode: aborting on feature page failure (${detailUrl})`);
      }
    }
    await sleep(delayMs);
  }

  return { extracted, skipped, failed };
}
