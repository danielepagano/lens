export type MetadataValueKind = 'text' | 'number' | 'list' | 'kv'

export interface MetadataListItem {
  id: string
  value: string
}

export interface MetadataKvItem {
  id: string
  key: string
  value: string
}

export interface MetadataFieldRow {
  id: string
  key: string
  kind: MetadataValueKind
  /** Used by 'text' and 'number' kinds. */
  text: string
  list: MetadataListItem[]
  kv: MetadataKvItem[]
}

export interface ReservedMetadata {
  relative_path: string
  name: string
  extension: string
  type: string
}
