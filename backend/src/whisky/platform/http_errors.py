"""Explicit opt-in to safe public API error formatting."""


class PublicAPIError(Exception):
    """Adapters supply a known public code, never arbitrary exception detail."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
