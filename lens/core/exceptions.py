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
