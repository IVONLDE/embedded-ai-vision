from __future__ import annotations

class BackendError(Exception):
    code = "BACKEND_ERROR"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class ValidationError(BackendError):
    code = "VALIDATION_ERROR"


class NotFoundError(BackendError):
    code = "NOT_FOUND"


class TaskCancellationRequested(BackendError):
    code = "CANCELLED"
