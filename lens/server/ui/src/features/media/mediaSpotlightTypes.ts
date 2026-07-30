export type MediaSpotlightMode = 'attach' | 'manage' | 'preview' | 'replace' | 'chromakey'

export type MediaSpotlightCallbacks = {
  onAttach?: () => void
  onDownload?: () => void
  onStartRename?: () => void
  onConfirmRename?: (value: string) => void
  onCancelRename?: () => void
  onDelete?: () => void
  onClose?: () => void
  onSave?: () => void
  onToggleChromeless?: () => void
}
