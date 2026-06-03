import { SvelteMap, SvelteSet } from 'svelte/reactivity'
import { getKbItems, getTree, browseMountDir } from '../../services/api'
import type { MountEntry, Stats, TreeNode } from '../../services/api'
import type { DataSources } from './CliAutocomplete'

export class CliDataSources {
  kbKeyCache = new SvelteMap<string, string[]>()
  nodeTreeCache: TreeNode[] | null = null
  nodeTreeFetchPending = false
  mountDirCache = new SvelteMap<string, MountEntry[]>()
  mountDirFetchPending = new SvelteSet<string>()

  resetTreeCaches(): void {
    this.nodeTreeCache = null
    this.nodeTreeFetchPending = false
    this.kbKeyCache = new SvelteMap()
  }

  resetMountCaches(): void {
    this.mountDirCache = new SvelteMap()
    this.mountDirFetchPending = new SvelteSet()
  }

  fetchKbKeys(type: string, onUpdate: () => void): void {
    if (this.kbKeyCache.has(type)) return
    getKbItems({ type })
      .then((items) => {
        const keys = items.map((item) => item.id.slice(item.id.indexOf('.') + 1))
        this.kbKeyCache = new SvelteMap(this.kbKeyCache).set(type, keys)
        onUpdate()
      })
      .catch(() => {
        this.kbKeyCache = new SvelteMap(this.kbKeyCache).set(type, [])
      })
  }

  fetchMountDir(path: string, onUpdate: () => void): void {
    if (this.mountDirFetchPending.has(path)) return
    this.mountDirFetchPending = new SvelteSet(this.mountDirFetchPending).add(path)
    browseMountDir(path)
      .then((entries) => {
        this.mountDirCache = new SvelteMap(this.mountDirCache).set(path, entries)
        onUpdate()
      })
      .catch(() => {
        this.mountDirCache = new SvelteMap(this.mountDirCache).set(path, [])
      })
      .finally(() => {
        const nextPending = new SvelteSet(this.mountDirFetchPending)
        nextPending.delete(path)
        this.mountDirFetchPending = nextPending
      })
  }

  fetchNodeTree(onUpdate: () => void): void {
    if (this.nodeTreeFetchPending || this.nodeTreeCache !== null) return
    this.nodeTreeFetchPending = true
    getTree()
      .then((tree) => {
        this.nodeTreeCache = tree
        onUpdate()
      })
      .catch(() => {
        this.nodeTreeCache = []
      })
      .finally(() => {
        this.nodeTreeFetchPending = false
      })
  }

  makeDataSources(
    stats: Stats | null,
    currentAddress: string | null,
    onUpdate: () => void,
  ): DataSources {
    const cursorAddr = stats?.cursor ?? null
    const viewingAtProjectCursor = cursorAddr === null || currentAddress === cursorAddr
    return {
      kbTypes: stats?.kb_types ?? [],
      kbKeyCache: this.kbKeyCache,
      fetchKbKeys: (type) => this.fetchKbKeys(type, onUpdate),
      nodeTree: this.nodeTreeCache,
      fetchNodeTree: () => this.fetchNodeTree(onUpdate),
      stats,
      mountDirCache: this.mountDirCache,
      fetchMountDir: (path) => this.fetchMountDir(path, onUpdate),
      viewingAtProjectCursor,
    }
  }
}
