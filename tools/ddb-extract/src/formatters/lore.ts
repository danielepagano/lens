import { toTagSlug, wrapKbBlock } from "./kb.js";
import type { LoreTocEntry } from "../parsers/lore-source.js";
import type { LoreChapterData } from "../parsers/lore-chapter.js";

export interface LoreIndexConfig {
  /** Short, dot-safe title slug used in KB ids, e.g. "grim-hollow". */
  titleKey: string;
}

export function formatLoreIndex(
  entries: LoreTocEntry[],
  config: LoreIndexConfig
): string {
  const id = `lore.${config.titleKey}`;

  // Tags on the index are used as a flat list of child lore ids.
  const childIds: string[] = [];

  const lines: string[] = [];

  lines.push(`# ${humanizeTitle(config.titleKey)}`);
  lines.push("");

  let currentPart: string | undefined;

  for (const entry of entries) {
    const slugPart = entry.href.split("/").filter(Boolean).pop() ?? "";
    const chapterId = buildChapterId(config.titleKey, entry.chapterNumber, slugPart);
    childIds.push(chapterId);

    const hasChapterNumber = entry.chapterNumber !== undefined;

    // Introduction (no part, no chapter number): treat as its own section
    if (!hasChapterNumber && !entry.partTitle) {
      lines.push(`## ${entry.title}`);
    } else {
      // Part heading
      if (entry.partTitle && entry.partTitle !== currentPart) {
        currentPart = entry.partTitle;
        lines.push("");
        lines.push(`## ${entry.partTitle}`);
      }

      const label = hasChapterNumber
        ? `Chapter ${entry.chapterNumber}: ${entry.title}`
        : entry.title;
      lines.push(`### ${label}`);
    }

    if (entry.subsections && entry.subsections.length) {
      for (const sub of entry.subsections) {
        lines.push(`- ${sub.title}`);
      }
    }

    lines.push("");
  }

  const body = lines.join("\n");
  return wrapKbBlock(id, childIds, body);
}

export function formatLoreChapter(
  chapter: LoreChapterData,
  entry: LoreTocEntry,
  config: LoreIndexConfig
): string {
  const slugPart = chapter.slug || (entry.href.split("/").filter(Boolean).pop() ?? "");
  const id = buildChapterId(config.titleKey, entry.chapterNumber, slugPart);

  const tags: string[] = [];

  const headingLabel =
    entry.chapterNumber !== undefined
      ? `Chapter ${entry.chapterNumber}: ${entry.title}`
      : entry.title;

  const header = `**${headingLabel}**`;

  const body = `${header}\n\n${chapter.body.trimEnd()}`;

  return wrapKbBlock(id, tags, body);
}

function humanizeTitle(key: string): string {
  return key
    .replace(/\./g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function buildChapterId(
  titleKey: string,
  chapterNumber: number | undefined,
  slugPart: string
): string {
  const cleanSlug = slugPart.split("?")[0];
  if (chapterNumber === undefined) {
    return `lore.${titleKey}-${cleanSlug}`;
  }
  return `lore.${titleKey}-${chapterNumber}-${cleanSlug}`;
}

