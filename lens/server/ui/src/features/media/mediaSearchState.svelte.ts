import { searchMedia, type SearchMediaItem } from '../../services/api'

/**
 * Search-mode state for the media carousel (#103): query, results,
 * pagination, and request lifecycle. Lives as its own reactive class so
 * MediaCarousel.svelte doesn't have to hold every field itself.
 *
 * Not cleared on `close()` — a query is remembered for as long as the
 * carousel component stays mounted (it never unmounts; see App.svelte),
 * i.e. until page reload. Only `clear()` (search box emptied) and
 * `resetForProjectSwitch()` drop it.
 */
export class MediaSearchState {
  open = $state(false)
  query = $state('')
  results = $state.raw<SearchMediaItem[]>([])
  page = $state(1)
  totalPages = $state(1)
  loading = $state(false)
  loadingMore = $state(false)
  error = $state<string | null>(null)
  /** Whether a search has actually been sent yet — gates the results pane
   * (incl. "No results") so a fresh/cleared search box shows nothing
   * rather than an empty state before the user has typed anything. */
  hasRun = $state(false)

  private requestSeq = 0

  get hasMore(): boolean {
    return this.page < this.totalPages
  }

  async performSearch(query: string, page: number): Promise<void> {
    const seq = ++this.requestSeq
    if (page === 1) {
      this.hasRun = true
      this.loading = true
      this.error = null
    } else {
      this.loadingMore = true
    }
    try {
      const result = await searchMedia(query, page)
      if (seq !== this.requestSeq) return
      this.results = page === 1 ? result.items : [...this.results, ...result.items]
      this.page = result.current_page
      this.totalPages = result.total_pages
    } catch (e) {
      if (seq !== this.requestSeq) return
      this.error = e instanceof Error ? e.message : String(e)
      if (page === 1) this.results = []
    } finally {
      if (seq === this.requestSeq) {
        this.loading = false
        this.loadingMore = false
      }
    }
  }

  loadMore(): void {
    if (this.loadingMore || this.page >= this.totalPages) return
    void this.performSearch(this.query, this.page + 1)
  }

  run(query: string): void {
    void this.performSearch(query, 1)
  }

  clear(): void {
    this.requestSeq++
    this.hasRun = false
    this.results = []
    this.error = null
    this.page = 1
    this.totalPages = 1
  }

  resetForProjectSwitch(): void {
    this.open = false
    this.query = ''
    this.requestSeq++
    this.hasRun = false
    this.results = []
    this.error = null
    this.page = 1
    this.totalPages = 1
  }
}
