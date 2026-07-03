from abc import ABC, abstractmethod
from typing import Any


class VoiceProvider(ABC):
    @abstractmethod
    async def create_call(self, to: str | None, metadata: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def accept_call(self, call_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def end_call(self, call_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_call_status(self, call_id: str) -> dict[str, Any]:
        raise NotImplementedError
