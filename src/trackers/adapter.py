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

    def __init__(self, factories: Mapping[str, Any], extensions: Mapping[str, Any] | None = None) -> None:
        self._factories = factories
        self._extensions: dict[str, Any] = {}
        for name, factory in (extensions or {}).items():
            normalized = self.normalize(name)
            if normalized in self._factories:
                raise ValueError(f"Extension tracker {normalized} conflicts with a built-in tracker")
            self._extensions[normalized] = factory

    @staticmethod
    def normalize(name: str) -> str:
        return name.replace(" ", "").upper().strip()

    def __getitem__(self, name: str) -> TrackerFactory:
        normalized = self.normalize(name)
        if normalized in self._factories:
            return self._factories[normalized]
        return self._extensions[normalized]

    def __iter__(self) -> Iterator[str]:
        return iter(dict.fromkeys((*self._factories, *self._extensions)))

    def __len__(self) -> int:
        return len(set(self._factories) | set(self._extensions))

    def create(self, name: str, config: dict[str, Any]) -> TrackerAdapter:
        factory = self[name]
        return factory(config=config)

    def by_auth_type(self, auth_type: str) -> set[str]:
        return {name for name in self if getattr(self[name], "auth_type", None) == auth_type}

    def supports(self, name: str, category: str) -> bool | None:
        try:
            factory = self[name]
        except KeyError:
            return None
        supported = getattr(factory, "supported_categories", None)
        if supported is None:
            return False
        normalized_category = category.upper()
        return any(str(candidate).upper() == normalized_category for candidate in supported)
