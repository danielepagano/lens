import { readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, resolve } from "path";
import type { SourceCatalog, SourceEntry } from "./types.js";
import type { DiscoveredSource } from "./parsers/source-filter.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SOURCES_PATH = resolve(__dirname, "../config/sources.json");

export function loadSources(): SourceCatalog {
  return JSON.parse(readFileSync(SOURCES_PATH, "utf-8")) as SourceCatalog;
}

export function resolveSource(slug: string): SourceEntry & { slug: string } {
  const sources = loadSources();
  const entry = sources[slug];
  if (!entry) {
    throw new Error(
      `Unknown source "${slug}". Run: ddb sources\n` +
        `To add a new source, run: ddb discover <slug>`
    );
  }
  if (entry.filterId === null) {
    throw new Error(
      `Source "${slug}" has no filter ID. Run: ddb discover ${slug}`
    );
  }
  return { ...entry, slug };
}

export function writeFilterId(slug: string, id: number): void {
  const sources = loadSources();
  if (!sources[slug]) {
    throw new Error(`Unknown source "${slug}"`);
  }
  sources[slug].filterId = id;
  writeFileSync(SOURCES_PATH, JSON.stringify(sources, null, 2) + "\n", "utf-8");
}

// Merge a flat list of discovered sources into sources.json.
//
// For each discovered source:
//   - If an existing entry already has that filterId, preserve it (no changes).
//   - Otherwise generate a slug from the source name and add a new entry
//     with types: [] — types must be set manually (the filter UI shows the
//     same 136 sources on all four list pages, so types can't be inferred).
//
// Returns { added } count.
export function mergeDiscoveredSources(
  discovered: DiscoveredSource[]
): { added: number } {
  const sources = loadSources();

  // Build a reverse map: filterId → existing slug
  const idToSlug = new Map<number, string>();
  for (const [slug, entry] of Object.entries(sources)) {
    if (entry.filterId !== null) idToSlug.set(entry.filterId, slug);
  }

  let added = 0;

  for (const { name, filterId } of discovered) {
    if (idToSlug.has(filterId)) continue;

    const slug = nameToSlug(name);
    const finalSlug = uniqueSlug(slug, sources);
    sources[finalSlug] = { name, filterId, types: [] };
    idToSlug.set(filterId, finalSlug);
    added++;
  }

  writeFileSync(SOURCES_PATH, JSON.stringify(sources, null, 2) + "\n", "utf-8");
  return { added };
}

function nameToSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/['']/g, "")           // drop apostrophes
    .replace(/[^a-z0-9]+/g, "-")   // non-alphanumeric → hyphen
    .replace(/^-+|-+$/g, "");       // trim leading/trailing hyphens
}

function uniqueSlug(base: string, catalog: SourceCatalog): string {
  if (!catalog[base]) return base;
  let i = 2;
  while (catalog[`${base}-${i}`]) i++;
  return `${base}-${i}`;
}
