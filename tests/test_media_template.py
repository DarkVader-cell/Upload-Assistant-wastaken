# ruff: noqa: S101, F401, F811 -- shared pytest fixtures
import json

import pytest
from aiohttp import web
from test_catalogue_media_web import make_plan, manager
from test_media_naming import info

from src.catalogue_media import cleaned_tags, planned_release_name
from src.catalogue_media_web import fingerprint
from src.media_naming import release_name
from src.media_template import DEFAULT_TEMPLATE, render_movie, validate_options


def test_unshackle_style_movie_name_and_custom_tag():
    legacy = release_name(info(), "Movie", 2020, "AMZN", "TEMPLATE")
    assert render_movie(legacy, "Movie", 2020, "AMZN", "MY_GROUP", DEFAULT_TEMPLATE) == "Movie.2020.1080p.AMZN.WEB-DL.DDP5.1.H.264-MY_GROUP.mkv"
    assert render_movie(legacy, "Movie", 2020, "AMZN", "", DEFAULT_TEMPLATE) == "Movie.2020.1080p.AMZN.WEB-DL.DDP5.1.H.264.mkv"
    assert render_movie(legacy, "Movie", 2020, "AMZN", "", "{title}.{year}.{hdr?}.{video}-{tag}") == "Movie.2020.H.264.mkv"


@pytest.mark.parametrize("template", ["../{title}", "{title.__class__}", "{title!r}", "{title}/{year}", "{title}:{year}", "{unknown}.{title}"])
def test_template_paths_expressions_unknown_variables_fail_closed(template):
    with pytest.raises(ValueError):
        validate_options(template=template)


@pytest.mark.parametrize("tags", [{"ENCODER": "mkvmerge"}, {"IMDB": "tt7654321"}, {"COMMENT": "CardinalDL"}, {"TITLE": "bad\x00value"}, {"GROUP": ["not a string"]}])
def test_reserved_and_unsafe_tags_cannot_be_forged(tags):
    with pytest.raises(ValueError):
        validate_options(tags=tags)


def test_documented_space_style_resolution_and_separate_atmos():
    legacy = release_name(info(atmos=True), "The Movie", 2020, "AMZN", "TEMPLATE")
    result = render_movie(legacy, "The Movie", 2020, "AMZN", "TAG", "{title} ({year}) {resolution} {audio_full} {atmos?} {video}-{tag}")
    assert result == "The Movie (2020) 1080 DDP5.1 Atmos H.264-TAG.mkv"


def test_explicit_tags_are_xml_escaped_and_identities_retained():
    data = cleaned_tags("", "tt1234567", 42, {"TITLE": "A & B", "GROUP": "CUSTOM"})
    assert b"A &amp; B" in data and b"CUSTOM" in data and b"tt1234567" in data


def test_actual_media_characteristics_supply_template(monkeypatch, tmp_path):
    monkeypatch.setattr("src.catalogue_media._run", lambda _argv: json.dumps(info()).encode())
    assert planned_release_name(tmp_path / "file.mkv", "Movie", 2020, "AMZN", "NEW", template=DEFAULT_TEMPLATE).endswith("H.264-NEW.mkv")


def test_media_preferences_persist_only_validated_fields(manager):
    value, _root, _file = manager
    value.preferences({"group": "MyGroup", "template": DEFAULT_TEMPLATE, "tags": {"COMMENT": "Reviewed"}})
    assert value.preferences()["group"] == "MyGroup"
    with pytest.raises(ValueError):
        value.preferences({"template": "../../{title}"})


@pytest.mark.asyncio
async def test_batch_guards_and_one_lease_for_all_files(manager, monkeypatch):
    value, root, source, preview = make_plan(manager, monkeypatch)
    second = root / "Second.2020.mkv"
    second.write_bytes(b"other source")
    plan = {**value.plans[preview["plan_id"]], "path": second.name, "fingerprint": fingerprint(second), "name": "Second.2020.mkv"}
    value.plans["second-plan"] = plan
    calls = []

    async def execute(item, release=True):
        assert value.lease is not None and release is False
        calls.append(item["name"])
        value.job = {"status": "succeeded", "filename": item["name"], "original_retained": True}

    monkeypatch.setattr(value, "execute", execute)
    with pytest.raises(web.HTTPBadRequest):
        await value.start_batch({"plan_ids": ["nonexistent-preview"]}, "owner")
    with pytest.raises(web.HTTPBadRequest):
        await value.start_batch({"plan_ids": [preview["plan_id"], preview["plan_id"]], "confirmation": "PROCESS COPY"}, "owner")
    await value.start_batch({"plan_ids": [preview["plan_id"], "second-plan"]}, "owner")
    await value.task
    assert len(calls) == 2 and value.job["completed"] == 2 and value.lease is None
    assert source.read_bytes() == b"synthetic-only" and second.read_bytes() == b"other source"


@pytest.mark.asyncio
async def test_batch_collision_and_changed_source_never_start(manager, monkeypatch):
    value, root, source, preview = make_plan(manager, monkeypatch)
    value.plans["duplicate"] = {**value.plans[preview["plan_id"]]}
    with pytest.raises(web.HTTPConflict):
        await value.start_batch({"plan_ids": [preview["plan_id"], "duplicate"], "confirmation": "PROCESS COPY"}, "owner")
    source.write_bytes(b"changed")
    with pytest.raises(web.HTTPConflict):
        await value.start_batch({"plan_ids": [preview["plan_id"]], "confirmation": "PROCESS COPY"}, "owner")
    assert not value.busy and not (root / "Processed").exists()
