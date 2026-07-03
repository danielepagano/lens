import { beforeAll, describe, it, expect } from 'vitest'
import type { Stats } from '../../services/api'
import { updateDatasetCommands } from '../../commands/handlers'
import {
  shouldSpaceSubmitEditReplace,
  shouldSpaceSubmitWriteManual,
  shouldSpaceSubmit,
} from './cliSubmitRules'

const MINIMAL_STATS: Stats = {
  active_narrative: 'story',
  narratives: ['story'],
  cursor: 'story',
  has_pending: false,
  has_staged: false,
  pending_owner: null,
  dataset_name: null,
  current_datasets: null,
  kb_types: [],
  kb_count: 0,
  effective_pins_at_cursor: null,
  effective_vars_at_cursor: {},
  effective_params_at_cursor: {},
  remember_pins_at_cursor: {},
  available_llms: [],
  image_backends: [],
  has_mount: false,
  cloud_mount: false,
  reference_images_supported: false,
  tts_available: false,
  active_session_operator: null,
  transaction: null,
  dataset_configs: {},
  release: null,
}

beforeAll(() => {
  updateDatasetCommands(MINIMAL_STATS)
})

describe('cliSubmitRules', () => {
  it('accepts complete /edit … --replace without prompt', () => {
    const cmd = '/edit / 10 20 --replace'
    expect(shouldSpaceSubmitEditReplace(cmd)).toBe(true)
    expect(shouldSpaceSubmit(cmd)).toBe(true)
  })

  it('rejects /edit --replace when prompt is present', () => {
    const cmd = '/edit / 10 20 --replace rewrite this'
    expect(shouldSpaceSubmitEditReplace(cmd)).toBe(false)
  })

  it('accepts /write --manual without prompt', () => {
    const cmd = '/write --manual'
    expect(shouldSpaceSubmitWriteManual(cmd)).toBe(true)
    expect(shouldSpaceSubmit(cmd)).toBe(true)
  })

  it('rejects /write --manual when prompt is present', () => {
    const cmd = '/write --manual continue the scene'
    expect(shouldSpaceSubmitWriteManual(cmd)).toBe(false)
  })
})
