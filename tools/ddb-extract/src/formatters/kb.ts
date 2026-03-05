// Shared slug helpers for KB key/tag derivation

/**
 * Convert a DnD Beyond URL slug to a KB key.
 * Strips leading numeric prefix: "2618987-fly" → "fly"
 * If stripping would produce an empty string or clash, retain full slug.
 */
export function slugifyKey(ddbSlug: string): string {
  const withoutPrefix = ddbSlug.replace(/^\d+-/, "");
  return withoutPrefix.length > 0 ? withoutPrefix : ddbSlug;
}

/**
 * Convert a display string to a valid tag slug.
 * Lowercase, replace spaces with hyphens, strip characters not in [a-zA-Z0-9_-].
 */
export function toTagSlug(str: string): string {
  return str
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9_-]/g, "")
    .replace(/^-+|-+$/g, ""); // trim leading/trailing hyphens
}

/**
 * Encode a CR value for use as a Lens tag.
 * Fractional CRs use hyphen notation (Lens tag values must match [a-zA-Z0-9_-]).
 *   "1/4" → "1-4"
 *   "1/2" → "1-2"
 *   "1/8" → "1-8"
 *   "5"   → "5"
 *   "0"   → "0"
 */
export function encodeCR(cr: string): string {
  return cr.replace("/", "-");
}

/**
 * Format an ordinal level description: 1 → "1st-level", 2 → "2nd-level", etc.
 * 0 → "Cantrip"
 */
export function levelLabel(level: number): string {
  if (level === 0) return "Cantrip";
  const suffixes: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };
  const suffix = suffixes[level] ?? "th";
  return `${level}${suffix}-level`;
}

/**
 * Capitalize first letter of each word.
 */
export function titleCase(str: string): string {
  return str.replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Wrap structured data in a ```kb fenced block.
 */
export function wrapKbBlock(
  id: string,
  tags: string[],
  body: string
): string {
  const tagLines = tags.map((t) => `  - ${t}`).join("\n");
  return (
    "```kb\n" +
    "---\n" +
    `id: ${id}\n` +
    "tags:\n" +
    tagLines +
    "\n---\n" +
    body.trimEnd() +
    "\n```"
  );
}
