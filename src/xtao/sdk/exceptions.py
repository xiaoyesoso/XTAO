"""XTAO SDK exceptions."""


class XTAOError(Exception):
    """Base exception for all SDK errors."""


class ConnectionError(XTAOError):
    """Raised when the SDK cannot connect to the XTAO server."""


class APIError(XTAOError):
    """Raised when the server returns an error response.

    Attributes:
        status_code: HTTP status code
        detail: Error detail message from the server
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class TimeoutError(XTAOError):
    """Raised when a request times out."""


class ValidationError(XTAOError):
    """Raised when request/response data fails validation."""
