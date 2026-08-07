# Extension API

The version 1 extension API adds fork-specific integrations without editing upstream-owned tracker modules. It is opt-in:

```python
"extensions_enabled": True,
"extension_paths": ["data/plugins"],
```

Each non-underscored Python file in an extension path exports `register(registry)`. Installed packages may instead publish a callable or object with `setup(registry)` in the `upload_assistant.extensions` entry-point group.

```python
from src.runtime.pipeline import StageResult


class AuditStage:
    name = "audit_release"

    async def run(self, context, meta):
        context.metrics.increment("extension.audit")
        return StageResult.completed()


def register(registry):
    if registry.api_version != 1:
        raise RuntimeError("Unsupported Upload Assistant extension API")
    registry.register_tracker("MYTRACKER", MyTracker)
    registry.register_provider("MYMETADATA", provider)
    registry.register_stage(AuditStage())
    registry.register_health_check("MYMETADATA", lambda: {"healthy": True})
```

Tracker factories use the existing `TrackerAdapter` contract: construction from the complete config plus the established `validate_credentials`, `search_existing`, `upload`, and description hooks required by their authentication type. Extension tracker names cannot conflict with built-ins. Duplicate tracker, provider, or health-check names fail during loading and appear in runtime health output.

Local extension files execute as application code and must be treated as trusted. Keep credentials in `data/config.py`; do not embed them in plugin files. Preparation checkpoints include extension stage names in their pipeline signature and are automatically invalidated when that ordered stage list changes.
