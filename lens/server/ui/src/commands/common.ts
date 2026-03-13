export type AutocompleteSource = 'narratives' | 'kb-ids' | 'nodes'

export interface StringField {
  kind: 'string'
  name: string
  hint?: string
  optional?: boolean
}

export interface BoolField {
  kind: 'bool'
  name: string
  label: string
  default?: boolean
}

export interface SelectField {
  kind: 'select'
  name: string
  label?: string
  options: { value: string; label: string }[]
  optional?: boolean
}

export interface AutocompleteField {
  kind: 'autocomplete'
  name: string
  label?: string
  hint?: string
  optional?: boolean
  source: AutocompleteSource
  repeatable?: boolean
}

export type FieldDef = StringField | BoolField | SelectField | AutocompleteField

export interface ConditionalFields {
  when: { field: string; value: string }
  then: FieldDef[]
}

export interface CommandFormSchema {
  hint?: string
  fields: FieldDef[]
  conditional?: ConditionalFields[]
}

export type CommandParams =
  | { kind: 'none' }
  | { kind: 'form'; schema: CommandFormSchema }

export type FieldValue = string | number | boolean | string[]
export type ResolvedParams = Record<string, FieldValue | undefined>

export interface CommandContext {
  setBusyMessage(message: string | null): void
  onDone?: () => Promise<void>
  resolvedParams?: ResolvedParams
}

export interface CommandResult {
  clearInput: boolean
}

export type CommandHandler = (
  command: string,
  payload: string,
  ctx: CommandContext
) => Promise<CommandResult>

export type CommandGroup = 'transactions' | 'cli' | (string & {})

export interface SubOption {
  value: string
}

export interface PayloadSuggestLevel {
  source: 'kb-types' | 'kb-keys'
  /** Character(s) appended to input after completing this level */
  separator: string
  /** For 'kb-keys': show all keys if total < threshold, otherwise require ≥1 char typed */
  threshold?: number
}

export interface PayloadSuggest {
  /** Character that separates levels within a single value (e.g. '.' in 'person.amy') */
  levelSeparator: string
  /** Character that separates multiple values in the payload (e.g. ' ') */
  valueSeparator: string
  levels: [PayloadSuggestLevel, PayloadSuggestLevel]
}

export interface PayloadOpt {
  /** Flag name without dashes, e.g. 'node' → '--node' in UI */
  flag: string
  hint?: string
}

export interface CommandDefinition {
  trigger: string
  group: CommandGroup
  hint?: string
  params?: CommandParams
  /** Sub-options shown as suggestion chips when payload is empty or a partial match */
  subOptions?: SubOption[]
  /** Hint shown in textarea ghost after a valid sub-option is selected */
  payloadHint?: string
  /** Multi-level inline autocomplete for the payload section after the sub-option */
  payloadSuggest?: PayloadSuggest
  /** Optional --flag parameters that can appear anywhere in the payload */
  payloadOpts?: PayloadOpt[]
}
