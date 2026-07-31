import { describe, it, expect, beforeEach } from 'vitest'
import { currentProject } from '../../stores/project'
import type { SuggestionApplyDeps } from './cliSuggestionApply'
import { CliDataSources } from './cliDataSources'
import { setupCliLifecycle, type CliLifecycleCtx } from './cliLifecycle'

const NOOP_SUGGESTION_APPLY_DEPS: SuggestionApplyDeps = {
  getInput: () => '',
  setInput: () => {},
  getActiveCommandDef: () => null,
  getCurrentParseState: () => null,
  getCliCaretHi: () => 0,
  setCliCaretHi: () => {},
  setPendingCliCaretHi: () => {},
  getNodeTreeCache: () => null,
  getCurrentAddress: () => null,
  navigate: undefined,
  updateCommandState: () => {},
  focusCliInput: () => {},
  getCliInputEl: () => null,
  afterTick: (fn) => fn(),
  trySubmitIfComplete: () => {},
}

function makeCtx(dataSources: CliDataSources): { ctx: CliLifecycleCtx; state: { lastProject: string | null } } {
  const state = { lastProject: null as string | null }
  const ctx: CliLifecycleCtx = {
    getInput: () => '',
    setInput: () => {},
    dataSources,
    updateCommandState: () => {},
    focusCliInput: () => {},
    resizeCliInput: () => {},
    suggestionApplyDeps: () => NOOP_SUGGESTION_APPLY_DEPS,
    getLastProject: () => state.lastProject,
    setLastProject: (project) => {
      state.lastProject = project
    },
    getLastSessionOperator: () => null,
    setLastSessionOperator: () => {},
    setSessionFillSuppressed: () => {},
    setLastAutoFilledCommand: () => {},
    getPrevCliNavAddress: () => undefined,
    setPrevCliNavAddress: () => {},
  }
  return { ctx, state }
}

describe('setupCliLifecycle — project switch cache reset', () => {
  beforeEach(() => {
    currentProject.set(null)
  })

  it('clears the mount/tree/kb suggestion caches whenever the active project changes', () => {
    const dataSources = new CliDataSources()
    dataSources.mountDirCache.set('', [{ name: 'old.png', is_dir: false }])
    dataSources.nodeTreeCache = []
    dataSources.kbKeyCache.set('person', ['amy'])

    const { ctx } = makeCtx(dataSources)
    const teardown = setupCliLifecycle(ctx)

    currentProject.set('project-a')

    expect(dataSources.mountDirCache.size).toBe(0)
    expect(dataSources.nodeTreeCache).toBeNull()
    expect(dataSources.kbKeyCache.size).toBe(0)

    // A remembered browse listing from project-a would 404 once we're
    // looking at project-b's mount — every switch must clear it, not just
    // the first one.
    dataSources.mountDirCache.set('', [{ name: 'a.png', is_dir: false }])
    currentProject.set('project-b')

    expect(dataSources.mountDirCache.size).toBe(0)

    teardown()
  })

  it('does not reset caches when the project store fires with an unchanged value', () => {
    currentProject.set('project-a')
    const dataSources = new CliDataSources()
    const { ctx } = makeCtx(dataSources)
    ctx.setLastProject('project-a')

    const teardown = setupCliLifecycle(ctx)
    // Subscribing itself clears caches as a side effect of the initial
    // fire (a freshly constructed CliDataSources() would be empty anyway)
    // — populate afterward so this test isolates the steady-state
    // "store re-fires with the same value" path.
    dataSources.mountDirCache.set('', [{ name: 'a.png', is_dir: false }])
    currentProject.set('project-a')

    expect(dataSources.mountDirCache.size).toBe(1)

    teardown()
  })
})
