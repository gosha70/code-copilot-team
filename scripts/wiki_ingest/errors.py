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
