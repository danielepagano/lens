export interface SpellData {
  name: string;
  slug: string;
  level: number; // 0 for cantrips
  school: string;
  castingTime: string;
  range: string;
  components: string;
  duration: string;
  isRitual: boolean;
  description: string;
  higherLevel?: string;
}

export interface AbilityScores {
  str: number;
  dex: number;
  con: number;
  int: number;
  wis: number;
  cha: number;
}

export interface MonsterData {
  name: string;
  slug: string;
  size: string;
  type: string;
  alignment: string;
  ac: string;
  hp: string;
  speed: string;
  abilities: AbilityScores;
  skills: string;
  senses: string;
  languages: string;
  cr: string; // raw string from page, e.g. "1/4", "5", "0"
  traits: string;
  actions: string;
  reactions?: string;
  legendaryActions?: string;
  description?: string;
  habitats: string[];
}

export interface ItemData {
  name: string;
  slug: string;
  rarity: string;
  itemType: string;
  requiresAttunement: boolean;
  description: string;
}

export interface EquipmentData {
  name: string;
  slug: string;
  category: string;
  cost?: string;
  damage?: string;
  weight?: string;
  properties?: string;
  armorClass?: string;
  strength?: string;
  stealth?: string;
  description: string;
}

export type FeatureParentKind = "class" | "species";

export interface FeatureData {
  parentKind: FeatureParentKind;
  parentSlug: string;
  parentName: string;
  subclassName?: string;
  subclassSlug?: string;
  subclassContentSlug?: string;
  featureName: string;
  featureSlug: string;
  body: string;
  sourceUrl: string;
}

export interface SourceEntry {
  name: string;
  filterId: number | null;
  types: string[];
}

export interface SourceCatalog {
  [slug: string]: SourceEntry;
}

export interface ListItem {
  slug: string;
  url: string;
  name: string;
  habitats?: string[];
}
