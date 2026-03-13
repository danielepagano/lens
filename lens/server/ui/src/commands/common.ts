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

export interface CommandDefinition {
  trigger: string
  group: CommandGroup
  hint?: string
  params?: CommandParams
  /** Sub-options shown as suggestion chips when payload is empty or a partial match */
  subOptions?: SubOption[]
  /** Hint shown in textarea ghost after a valid sub-option is selected */
  payloadHint?: string
}
