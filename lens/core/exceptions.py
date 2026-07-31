"""Core exceptions for Lens."""


class LensException(Exception):
    """Base exception for all domain logic errors in Lens."""


class ValidationError(LensException):
    """Raised when operator preconditions are not met and no work was done.

    Unlike :class:`OperatorError`, a ``ValidationError`` guarantees that no
    state was changed — inputs were invalid, preconditions failed, or the
    combination of parameters was not actionable.  Callers should surface the
    error without attempting rollback or cleanup.
    """


class OperatorError(LensException):
    """Raised when an operator encounters a runtime failure.

    An ``OperatorError`` may be raised after partial state changes (e.g. an LLM
    call fails after content was written, or a retry discard leaves the working
    tree modified).  Callers should consider rolling back the pending
    transaction before surfacing the error.
    """


class MediaSearchCapacityExceeded(LensException):
    """Raised when a project's media file count exceeds the search index cap.

    The index (``lens.core.media.cache.MediaSearchIndex``) is deliberately
    all-or-nothing: rather than partially index the project or fall back to
    per-file backend reads during search, it locks itself empty once file
    count passes the configured limit. Raise ``[project]
    media_search_index_limit`` in ``lens.toml`` and retry.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(
            f"media search index is over capacity (limit={limit} files) — "
            f"increase [project] media_search_index_limit in lens.toml"
        )
