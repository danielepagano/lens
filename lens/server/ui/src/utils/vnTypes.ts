/** Scene (VN) TTS behavior — encoded in URL (`vn_spk`, `vn_aa`, `vn_rdr`) and session. */
export interface VnTtsSettings {
  /** Master: TTS can play in Scene. When false, no playback and you advance manually only. */
  speak: boolean
  /** When TTS for the current beat ends, advance to the next beat (no effect if there was no TTS). */
  autoAdvance: boolean
  /** Request TTS via stream when uncached; with auto-advance, after playback starts POST `/tts/render` for the next text chunk (optimistically marked cached client-side). */
  renderNew: boolean
}

export const DEFAULT_VN_TTS: VnTtsSettings = {
  speak: false,
  autoAdvance: false,
  renderNew: false,
}
