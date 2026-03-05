import { existsSync, readFileSync, writeFileSync, appendFileSync } from "fs";
import { mkdirSync } from "fs";
import { dirname } from "path";

export function createOutputFile(
  path: string,
  source: string,
  type: string,
  enumerateCount: number
): void {
  mkdirSync(dirname(path), { recursive: true });
  const started = new Date().toISOString();
  const header =
    `# DnD Beyond Extract: ${source} / ${type}\n` +
    `<!-- source:${source} | type:${type} | started:${started} | enumerate:${enumerateCount} -->\n\n`;
  writeFileSync(path, header, "utf-8");
}

export function scanDoneSet(path: string): Set<string> {
  const done = new Set<string>();
  if (!existsSync(path)) return done;
  const content = readFileSync(path, "utf-8");
  // Match `id: some.key` inside ```kb fences
  const blockRe = /^```kb\n([\s\S]*?)^```/gm;
  const idRe = /^id:\s*(.+)$/m;
  let match: RegExpExecArray | null;
  while ((match = blockRe.exec(content)) !== null) {
    const idMatch = idRe.exec(match[1]);
    if (idMatch) {
      done.add(idMatch[1].trim());
    }
  }
  return done;
}

export function appendBlock(path: string, kbBlock: string): void {
  appendFileSync(path, kbBlock + "\n", "utf-8");
}

export function appendFailure(path: string, slug: string, reason: string): void {
  const line = `<!-- FAILED: ${slug} | reason: ${reason.replace(/-->/g, "--&gt;")} -->\n`;
  appendFileSync(path, line, "utf-8");
}
