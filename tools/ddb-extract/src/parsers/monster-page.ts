import type { Page } from "playwright";
import type { MonsterData, AbilityScores } from "../types.js";

// Monster detail page: https://www.dndbeyond.com/monsters/{slug}
//
// Confirmed selectors (verified 2026-03-04 against live DOM):
//   Name:           .page-title  (is an H1 element)
//   Meta:           .mon-stat-block__meta  ("Medium Humanoid (Aarakocra), Neutral Good")
//   Attributes:     .mon-stat-block__attribute → label + .mon-stat-block__attribute-data-value
//   Ability scores: .ability-block__stat--{str|dex|con|int|wis|cha} → .ability-block__score
//   Tidbits:        .mon-stat-block__tidbit → .mon-stat-block__tidbit-label + -data
//   Desc blocks:    .mon-stat-block__description-block →
//                     .mon-stat-block__description-block-heading + -content
//
// IMPORTANT: do not use named function variables (const f = () => {}) inside page.evaluate —
// esbuild's keepNames injects __name() calls that are undefined in the browser context.
// Use only inline expressions and anonymous callbacks.

export async function parseMonsterPage(
  page: Page,
  habitats: string[]
): Promise<MonsterData> {
  await page
    .waitForSelector(".mon-stat-block, .monster-details", {
      timeout: 15000,
    })
    .catch(() => {
      throw new Error(`Monster page did not render stat block at ${page.url()}`);
    });

  return page.evaluate(
    (habitats: string[]): MonsterData => {
      // Name
      const name =
        document.querySelector(".page-title")?.textContent?.trim() ?? "";

      // Meta: "Medium Humanoid (Aarakocra), Neutral Good"
      const meta =
        document.querySelector(".mon-stat-block__meta")?.textContent?.trim() ?? "";
      const metaParts = meta.split(",");
      const sizeType = metaParts[0]?.trim() ?? "";
      const alignment = metaParts.slice(1).join(",").trim();
      const sizeTypeWords = sizeType.split(/\s+/);
      const size = sizeTypeWords[0]?.toLowerCase() ?? "medium";
      const type = sizeTypeWords
        .slice(1)
        .join(" ")
        .toLowerCase()
        .replace(/\s*\([^)]*\)/g, "")
        .trim();

      // AC, HP, Speed
      let ac = "";
      let hp = "";
      let speed = "";
      document.querySelectorAll(".mon-stat-block__attribute").forEach((row) => {
        const lbl =
          row.querySelector(".mon-stat-block__attribute-label")?.textContent?.trim().toLowerCase() ??
          "";
        const val =
          row.querySelector(".mon-stat-block__attribute-data-value")?.textContent?.trim() ?? "";
        if (lbl.includes("armor")) ac = val;
        else if (lbl.includes("hit points")) hp = val;
        else if (lbl.includes("speed")) speed = val;
      });

      // Ability scores — inline per ability to avoid named function variables
      const abilities: AbilityScores = {
        str:
          parseInt(
            document
              .querySelector(".ability-block__stat--str .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10,
        dex:
          parseInt(
            document
              .querySelector(".ability-block__stat--dex .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10,
        con:
          parseInt(
            document
              .querySelector(".ability-block__stat--con .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10,
        int:
          parseInt(
            document
              .querySelector(".ability-block__stat--int .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10,
        wis:
          parseInt(
            document
              .querySelector(".ability-block__stat--wis .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10,
        cha:
          parseInt(
            document
              .querySelector(".ability-block__stat--cha .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10,
      };

      // Tidbits
      let skills = "";
      let senses = "";
      let languages = "";
      let crRaw = "";
      document.querySelectorAll(".mon-stat-block__tidbit").forEach((tidbit) => {
        const lbl =
          tidbit
            .querySelector(".mon-stat-block__tidbit-label")
            ?.textContent?.trim()
            .toLowerCase() ?? "";
        const val =
          tidbit.querySelector(".mon-stat-block__tidbit-data")?.textContent?.trim() ?? "";
        if (lbl.includes("skill")) skills = val;
        else if (lbl.includes("sense")) senses = val;
        else if (lbl.includes("language")) languages = val;
        else if (lbl.includes("challenge")) crRaw = val;
      });

      const crMatch = crRaw.match(/^([0-9/]+)/);
      const cr = crMatch ? crMatch[1] : crRaw.split("(")[0].trim() || "0";

      // Description blocks: scan blocks by heading, collect paragraph text
      let traits = "";
      let actions = "";
      let reactions = "";
      let legendaryActions = "";

      document.querySelectorAll(".mon-stat-block__description-block").forEach((block) => {
        const heading =
          block
            .querySelector(".mon-stat-block__description-block-heading")
            ?.textContent?.trim()
            .toLowerCase() ?? "";
        const content = block.querySelector(".mon-stat-block__description-block-content");
        if (!content) return;

        const paras = Array.from(content.querySelectorAll("p"));
        const blockText =
          paras.length > 0
            ? paras
                .map((p) => p.textContent?.trim() ?? "")
                .filter((t) => t.length > 0)
                .join("\n\n")
            : content.textContent?.trim() ?? "";

        if ((heading.includes("trait") || heading.includes("feature")) && !traits)
          traits = blockText;
        else if (heading.includes("action") && !heading.includes("legendary") && !actions)
          actions = blockText;
        else if (heading.includes("reaction") && !reactions) reactions = blockText;
        else if (heading.includes("legendary") && !legendaryActions) legendaryActions = blockText;
      });

      const slug = window.location.pathname.split("/").pop() ?? "";

      return {
        name: name || slug,
        slug,
        size,
        type: type || "unknown",
        alignment: alignment || "unaligned",
        ac: ac || "unknown",
        hp: hp || "unknown",
        speed: speed || "unknown",
        abilities,
        skills,
        senses,
        languages,
        cr,
        traits,
        actions,
        reactions: reactions || undefined,
        legendaryActions: legendaryActions || undefined,
        habitats,
      };
    },
    habitats
  );
}
