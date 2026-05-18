# wiki_ingest.errors — exception hierarchy with spec-defined exit codes.


class IngestError(Exception):
    """Base class for all wiki-ingest pipeline errors."""
    exit_code: int = 1


class BackendNotFoundError(IngestError):
    """No registered backend was found (auto-detect or explicit name). Exit 2."""
    exit_code: int = 2


class BackendInvocationError(IngestError):
    """Backend process exited non-zero. Exit 3."""
    exit_code: int = 3


class ContractViolationError(IngestError):
    """Backend response failed shape or semantic validation. Exit 4."""
    exit_code: int = 4


class SourceMissingError(IngestError):
    """Source file is missing or unreadable. Exit 5."""
    exit_code: int = 5


class OutputWriteError(IngestError):
    """Could not write the proposal file to the output directory. Exit 6."""
    exit_code: int = 6


class PromoteValidationError(IngestError):
    """Phase-2 promote: staged-tree validation failed (per-edit semantic
    or structural-lint). The wiki tree is unchanged on disk; the curator
    fixes the patch-set and reruns. Exit 9."""
    exit_code: int = 9


class PromoteApplyError(IngestError):
    """Phase-2 promote: filesystem failure during stage→wiki commit
    (rare; usually means the wiki dir is read-only or a TOCTOU race).
    Exit 10."""
    exit_code: int = 10


class AuditFlushError(IngestError):
    """wiki audit-flush: not a git work tree; append-only invariant violated;
    working log malformed; or git commit failed. Exit 11."""
    exit_code: int = 11
