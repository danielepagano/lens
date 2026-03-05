import type { Page } from "playwright";
import type { MonsterData, AbilityScores } from "../types.js";

// Monster detail page: https://www.dndbeyond.com/monsters/{slug}
//
// Two layouts: legacy (mon-stat-block) and 2024 (mon-stat-block-2024).
// 2024 selectors (MM 2025, etc.):
//   Container:   .mon-stat-block-2024
//   Meta:        .mon-stat-block-2024__meta
//   Attributes:  .mon-stat-block-2024__attribute → label + .mon-stat-block-2024__attribute-data-value
//   Ability:     .mon-stat-block-2024__stats table.stat-table th + td (first td = score)
//   Tidbits:     .mon-stat-block-2024__tidbit → -tidbit-label + -tidbit-data
//   Desc blocks: .mon-stat-block-2024__description-block → -heading + -content
// Lore: .more-info-content (outside stat block) or .mon-details__description-block-content
// Habitats: footer p.tags.environment-tags span.tag.environment-tag (detail page only)
//
// Legacy: .mon-stat-block__meta, .mon-stat-block__attribute, .ability-block__stat--str, etc.

export async function parseMonsterPage(
  page: Page,
  habitats: string[]
): Promise<MonsterData> {
  await page
    .waitForSelector(".mon-stat-block, .mon-stat-block-2024, .monster-details", {
      timeout: 15000,
    })
    .catch(() => {
      throw new Error(`Monster page did not render stat block at ${page.url()}`);
    });

  return page.evaluate(
    (habitats: string[]): MonsterData => {
      const slug = window.location.pathname.split("/").pop() ?? "";
      const name =
        (document.querySelector(".page-title")?.textContent?.trim() ?? "") || slug;

      const is2024 = !!document.querySelector(".mon-stat-block-2024");

      let meta = "";
      let ac = "";
      let hp = "";
      let speed = "";
      let skills = "";
      let senses = "";
      let languages = "";
      let crRaw = "";
      const abilities: AbilityScores = { str: 10, dex: 10, con: 10, int: 10, wis: 10, cha: 10 };
      let traits = "";
      let actions = "";
      let reactions = "";
      let legendaryActions = "";
      let description = "";

      if (is2024) {
        const metaEl = document.querySelector(".mon-stat-block-2024__meta");
        meta = metaEl?.textContent?.trim() ?? "";

        document.querySelectorAll(".mon-stat-block-2024__attribute").forEach((row) => {
          const labels = Array.from(row.querySelectorAll(".mon-stat-block-2024__attribute-label"));
          const values = Array.from(
            row.querySelectorAll(".mon-stat-block-2024__attribute-data-value")
          );
          labels.forEach((lbl, i) => {
            const text = lbl.textContent?.trim().toLowerCase() ?? "";
            const val = values[i]?.textContent?.trim() ?? "";
            if (text.includes("armor") || text === "ac") ac = val;
            else if (text.includes("hit") || text === "hp") hp = val;
            else if (text.includes("speed")) speed = val;
          });
        });

        document.querySelectorAll(".mon-stat-block-2024__stats table.stat-table").forEach((tbl) => {
          tbl.querySelectorAll("tbody tr").forEach((tr) => {
            const th = tr.querySelector("th");
            const firstTd = tr.querySelector("td");
            const score = parseInt(firstTd?.textContent?.trim() ?? "10") || 10;
            const key = th?.textContent?.trim().toLowerCase().slice(0, 3) ?? "";
            if (key === "str") abilities.str = score;
            else if (key === "dex") abilities.dex = score;
            else if (key === "con") abilities.con = score;
            else if (key === "int") abilities.int = score;
            else if (key === "wis") abilities.wis = score;
            else if (key === "cha") abilities.cha = score;
          });
        });

        document.querySelectorAll(".mon-stat-block-2024__tidbit").forEach((tidbit) => {
          const lbl =
            tidbit
              .querySelector(".mon-stat-block-2024__tidbit-label")
              ?.textContent?.trim()
              .toLowerCase() ?? "";
          const val =
            tidbit.querySelector(".mon-stat-block-2024__tidbit-data")?.textContent?.trim() ?? "";
          if (lbl.includes("skill")) skills = val;
          else if (lbl.includes("sense")) senses = val;
          else if (lbl.includes("language")) languages = val;
          else if (lbl.includes("cr") || lbl === "cr") crRaw = val;
        });

        document
          .querySelectorAll(".mon-stat-block-2024__description-block")
          .forEach((block) => {
            const heading =
              block
                .querySelector(".mon-stat-block-2024__description-block-heading")
                ?.textContent?.trim()
                .toLowerCase() ?? "";
            const content = block.querySelector(
              ".mon-stat-block-2024__description-block-content"
            );
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

        const descEl =
          document.querySelector(".more-info-content .mon-details__description-block-content") ??
          document.querySelector(".more-info-content");
        if (descEl) {
          const blocks: string[] = [];
          descEl.querySelectorAll("p").forEach((p) => {
            const t = p.textContent?.trim() ?? "";
            if (t.length > 0) blocks.push(t);
          });
          description = blocks.join("\n\n");
        }
      } else {
        meta =
          document.querySelector(".mon-stat-block__meta")?.textContent?.trim() ?? "";
        document.querySelectorAll(".mon-stat-block__attribute").forEach((row) => {
          const lbl =
            row
              .querySelector(".mon-stat-block__attribute-label")
              ?.textContent?.trim()
              .toLowerCase() ?? "";
          const val =
            row
              .querySelector(".mon-stat-block__attribute-data-value")
              ?.textContent?.trim() ?? "";
          if (lbl.includes("armor")) ac = val;
          else if (lbl.includes("hit points")) hp = val;
          else if (lbl.includes("speed")) speed = val;
        });
        abilities.str =
          parseInt(
            document
              .querySelector(".ability-block__stat--str .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10;
        abilities.dex =
          parseInt(
            document
              .querySelector(".ability-block__stat--dex .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10;
        abilities.con =
          parseInt(
            document
              .querySelector(".ability-block__stat--con .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10;
        abilities.int =
          parseInt(
            document
              .querySelector(".ability-block__stat--int .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10;
        abilities.wis =
          parseInt(
            document
              .querySelector(".ability-block__stat--wis .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10;
        abilities.cha =
          parseInt(
            document
              .querySelector(".ability-block__stat--cha .ability-block__score")
              ?.textContent?.trim() ?? "10"
          ) || 10;
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
      }

      const crMatch = crRaw.match(/^([0-9/]+)/);
      const cr = crMatch ? crMatch[1] : crRaw.split("(")[0].trim() || "0";
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

      const habitatEls = document.querySelectorAll(
        "footer p.tags.environment-tags span.tag.environment-tag"
      );
      const pageHabitats = Array.from(habitatEls)
        .map((el) => el.textContent?.trim() ?? "")
        .filter((t) => t.length > 0);
      const finalHabitats = pageHabitats.length > 0 ? pageHabitats : habitats;

      return {
        name,
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
        description: description || undefined,
        habitats: finalHabitats,
      };
    },
    habitats
  );
}
