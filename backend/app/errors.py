"""Error type and user-facing messages.

Pure Python on purpose: no web-framework imports, because the worker process uses it too.
Every error the API returns has this JSON shape:

    {"error": {"code": "wrong_password", "message": "...", "retry_after": 30}}

("retry_after" is only present for rate_limited and server_busy.)
"""
from __future__ import annotations

USER_MESSAGES: dict[str, str] = {
    # Request-level errors (HTTP status != 2xx)
    "invalid_request": "The request was not valid. Please update the app and try again.",
    "invalid_options": "Some of the options you chose are not valid.",
    "invalid_files": "The number of files is not right for this tool.",
    "unknown_tool": "This tool is not available.",
    "unsupported_type": "This file type is not supported by this tool.",
    "file_too_large": "One of the files is too large.",
    "job_too_large": "The files together are too large.",
    "rate_limited": "You have made a lot of requests. Please wait a bit and try again.",
    "server_busy": "The server is busy right now. Please try again in a minute.",
    "job_not_found": "We could not find this job. Please run the operation again.",
    "job_expired": "This result has expired or was already downloaded. Please run the operation again.",
    "result_not_ready": "The result is not ready yet.",
    "internal_error": "Something went wrong on our side. Please try again.",
    # Job-level errors (reported inside a failed job)
    "wrong_password": "That password is incorrect. Please try again.",
    "password_required": "This PDF is password-protected. Please enter its password.",
    "corrupted_file": "This file looks damaged and could not be read.",
    "job_timeout": "This took too long to process. Try a smaller file or fewer pages.",
    "worker_crashed": "The file could not be processed. It may be damaged or too complex.",
    "too_complex": "This file is too complex for the free server. Try a smaller file or fewer pages.",
    "output_too_large": "The result would be too large. Try fewer pages or a lower quality.",
    "processing_failed": "The file could not be processed.",
}

class AppError(Exception):
    """An error that becomes a consistent JSON response."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str | None = None,
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message or USER_MESSAGES.get(code, USER_MESSAGES["internal_error"])
        self.retry_after = retry_after

    def body(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            error["retry_after"] = self.retry_after
        return {"error": error}
