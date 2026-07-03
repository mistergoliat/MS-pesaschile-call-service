from typing import Any


class AppError(Exception):
    def __init__(
        self,
        error: str,
        detail: str,
        *,
        status_code: int = 400,
        payload: Any = None,
    ) -> None:
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.status_code = status_code
        self.payload = payload
