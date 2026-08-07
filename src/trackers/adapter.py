"""Compatibility contracts and registry for tracker implementations."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from src.meta import Meta


class TrackerFactory(Protocol):
    def __call__(self, config: dict[str, Any]) -> TrackerAdapter: ...


@runtime_checkable
class TrackerAdapter(Protocol):
    """Minimum behavior consumed by shared tracker orchestration."""

    tracker: str
    auth_type: str
    supported_categories: Sequence[str]
    is_usenet: bool

    async def search_existing(self, meta: Meta) -> list[Any]: ...
    async def upload(self, meta: Meta) -> bool | None: ...


class TrackerRegistry(Mapping[str, TrackerFactory]):
    """Normalized view over the legacy mutable tracker class dictionary."""

    def __init__(self, factories: Mapping[str, Any]) -> None:
        self._factories = factories

    @staticmethod
    def normalize(name: str) -> str:
        return name.replace(" ", "").upper().strip()

    def __getitem__(self, name: str) -> TrackerFactory:
        return self._factories[self.normalize(name)]

    def __iter__(self) -> Iterator[str]:
        return iter(self._factories)

    def __len__(self) -> int:
        return len(self._factories)

    def create(self, name: str, config: dict[str, Any]) -> TrackerAdapter:
        factory = self[name]
        return factory(config=config)

    def by_auth_type(self, auth_type: str) -> set[str]:
        return {
            name
            for name, factory in self._factories.items()
            if getattr(factory, "auth_type", None) == auth_type
        }

    def supports(self, name: str, category: str) -> bool | None:
        factory = self._factories.get(self.normalize(name))
        if factory is None:
            return None
        supported = getattr(factory, "supported_categories", None)
        if supported is None:
            return False
        normalized_category = category.upper()
        return any(str(candidate).upper() == normalized_category for candidate in supported)
