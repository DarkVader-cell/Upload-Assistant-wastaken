"""Stable, opt-in extension API kept outside upstream-owned tracker modules."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

EXTENSION_API_VERSION = 1
ENTRY_POINT_GROUP = "upload_assistant.extensions"


class Extension(Protocol):
    def setup(self, registry: ExtensionRegistry) -> None: ...


@dataclass(slots=True)
class ExtensionRegistry:
    api_version: int = EXTENSION_API_VERSION
    trackers: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)
    pipeline_stages: list[Any] = field(default_factory=list)
    health_checks: dict[str, Callable[[], Mapping[str, Any]]] = field(default_factory=dict)
    loaded: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _name(value: str) -> str:
        normalized = value.replace(" ", "").upper().strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,63}", normalized):
            raise ValueError(f"Invalid extension component name: {value!r}")
        return normalized

    def register_tracker(self, name: str, factory: Any) -> None:
        normalized = self._name(name)
        if normalized in self.trackers:
            raise ValueError(f"Extension tracker {normalized} is already registered")
        self.trackers[normalized] = factory

    def register_provider(self, name: str, provider: Any) -> None:
        normalized = self._name(name)
        if normalized in self.providers:
            raise ValueError(f"Extension provider {normalized} is already registered")
        self.providers[normalized] = provider

    def register_stage(self, stage: Any) -> None:
        if not getattr(stage, "name", None) or not callable(getattr(stage, "run", None)):
            raise TypeError("Extension stages require a name and async run(context, meta) method")
        self.pipeline_stages.append(stage)

    def register_health_check(self, name: str, check: Callable[[], Mapping[str, Any]]) -> None:
        normalized = self._name(name)
        if normalized in self.health_checks:
            raise ValueError(f"Extension health check {normalized} is already registered")
        self.health_checks[normalized] = check

    def snapshot(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version,
            "loaded": list(self.loaded),
            "errors": dict(self.errors),
            "trackers": sorted(self.trackers),
            "providers": sorted(self.providers),
            "stages": [str(stage.name) for stage in self.pipeline_stages],
        }


_REGISTRIES: dict[tuple[str, str], ExtensionRegistry] = {}


def _configure_module(module: ModuleType, registry: ExtensionRegistry) -> None:
    register = getattr(module, "register", None)
    extension = getattr(module, "extension", None)
    if callable(register):
        register(registry)
    elif extension is not None and callable(getattr(extension, "setup", None)):
        extension.setup(registry)
    else:
        raise TypeError("extension must export register(registry) or extension.setup(registry)")


def _load_file(path: Path, registry: ExtensionRegistry) -> None:
    module_name = f"upload_assistant_extension_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load extension file {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _configure_module(module, registry)


def load_extensions(base_dir: str | Path, config: Mapping[str, Any], *, force: bool = False) -> ExtensionRegistry:
    default = config.get("DEFAULT", {}) if isinstance(config, Mapping) else {}
    settings = default if isinstance(default, Mapping) else {}
    enabled = bool(settings.get("extensions_enabled", False))
    raw_paths = settings.get("extension_paths", ["data/plugins"])
    paths = [raw_paths] if isinstance(raw_paths, str) else list(raw_paths) if isinstance(raw_paths, list | tuple) else []
    signature = (str(Path(base_dir).resolve()), repr((enabled, paths)))
    if not force and signature in _REGISTRIES:
        return _REGISTRIES[signature]
    registry = ExtensionRegistry()
    _REGISTRIES[signature] = registry
    if not enabled:
        return registry

    for entry_point in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded = entry_point.load()
            if callable(loaded):
                loaded(registry)
            elif callable(getattr(loaded, "setup", None)):
                loaded.setup(registry)
            else:
                raise TypeError("entry point must be callable or expose setup")
            registry.loaded.append(f"entry-point:{entry_point.name}")
        except Exception as error:
            registry.errors[f"entry-point:{entry_point.name}"] = str(error)

    root = Path(base_dir).resolve()
    for configured in paths:
        directory = Path(str(configured)).expanduser()
        directory = directory if directory.is_absolute() else root / directory
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            label = f"file:{path.name}"
            try:
                _load_file(path, registry)
                registry.loaded.append(label)
            except Exception as error:
                registry.errors[label] = str(error)
    return registry
