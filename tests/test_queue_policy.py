"""Regression tests for unattended queue-edit policy."""

from src.queue_policy import should_prompt_for_queue_edits


def test_attended_queue_operations_may_prompt():
    assert should_prompt_for_queue_edits({"unattended": False}) is True  # noqa: S101


def test_unattended_queue_operations_do_not_prompt():
    assert should_prompt_for_queue_edits({"unattended": True, "unattended_confirm": False}) is False  # noqa: S101


def test_unattended_confirmed_queue_operations_may_prompt():
    assert should_prompt_for_queue_edits({"unattended": True, "unattended_confirm": True}) is True  # noqa: S101
