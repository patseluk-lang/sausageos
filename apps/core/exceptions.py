class BusinessError(Exception):
    """A business rule violation, returned to the client as HTTP 400."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InsufficientStock(BusinessError):
    """Not enough raw material or finished goods in stock."""
