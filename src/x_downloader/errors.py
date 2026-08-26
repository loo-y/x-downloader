from __future__ import annotations


class XDownloaderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(XDownloaderError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("VALIDATION_ERROR", message, details=details)


class CredentialError(XDownloaderError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("CREDENTIAL_ERROR", message, details=details)


class ResolveError(XDownloaderError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("RESOLVE_ERROR", message, details=details)


class DownloadFailure(XDownloaderError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("DOWNLOAD_ERROR", message, details=details)


class DependencyError(XDownloaderError):
    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__("DEPENDENCY_ERROR", message, details=details)


class CancelledError(XDownloaderError):
    def __init__(self, message: str = "Download was cancelled.") -> None:
        super().__init__("CANCELLED", message)
