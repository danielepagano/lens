import type { FeatureData } from "../types.js";
import { wrapKbBlock } from "./kb.js";

export function formatFeature(data: FeatureData): string {
  const idCore = data.subclassSlug
    ? `${data.parentSlug}-${data.subclassSlug}-${data.featureSlug}`
    : `${data.parentSlug}-${data.featureSlug}`;
  const id = `feature.${idCore}`;
  const tags = [`${data.parentKind}:${data.parentSlug}`];
  if (data.subclassSlug) tags.push(`sublass:${data.subclassSlug}`);
  const title = data.subclassName
    ? `${data.featureName} (${data.subclassName})`
    : data.featureName;
  const body = `# ${title}\n\n${data.body}`.trimEnd();
  return wrapKbBlock(id, tags, body);
}
