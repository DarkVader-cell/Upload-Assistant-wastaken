"""Pure presentation and validation helpers for WebUI configuration options."""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any


def group_webui_default_settings(prepared: Mapping[str, Any], subsection_map: MutableMapping[str, str]) -> dict[str, Any]:
    """Group statistics and WebUI defaults without changing their saved paths."""
    prepared_options = dict(prepared)
    if "stats_enabled" in prepared_options:
        subsection_map["DEFAULT/stats_enabled"] = "MAIN SETTINGS"
        main_settings = {key: value for key, value in prepared_options.items() if subsection_map.get(f"DEFAULT/{key}") == "MAIN SETTINGS"}
        prepared_options = {**main_settings, **prepared_options}

    webui_settings = {key: value for key, value in prepared_options.items() if key.startswith("webui_")}
    for key in webui_settings:
        subsection_map[f"DEFAULT/{key}"] = "WEBUI SETTINGS"
    main_settings = {key: value for key, value in prepared_options.items() if subsection_map.get(f"DEFAULT/{key}") == "MAIN SETTINGS"}
    other_settings = {key: value for key, value in prepared_options.items() if key not in main_settings and key not in webui_settings}
    return {**main_settings, **webui_settings, **other_settings}


def prompt_timeout_example(path: Sequence[str], raw_value: object, example_value: object) -> object:
    """Allow finite non-negative fractional minutes for the unattended prompt timeout."""
    if list(path) != ["DEFAULT", "webui_unattended_prompt_timeout"]:
        return example_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (str, int, float)) or (isinstance(raw_value, str) and not raw_value.strip()):
        raise ValueError("Enter a timeout in minutes, or 0 to wait indefinitely")
    return 60.0


def validate_prompt_timeout(path: Sequence[str], value: object) -> None:
    """Reject invalid prompt timeouts after ordinary configuration coercion."""
    if list(path) != ["DEFAULT", "webui_unattended_prompt_timeout"]:
        return
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError("Unattended prompt timeout must be a finite number of minutes greater than or equal to 0")
