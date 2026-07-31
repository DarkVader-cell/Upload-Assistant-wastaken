import asyncio

from cogs.redaction import Redaction
from src.manual_metadata import metadata_request, parse_metadata_submission, should_request_metadata
from src.modified_release import MODIFIED_RELEASE_REASON, detect_modified_release
from src.safe_url import UnsafeURL, assert_public_http_url


def test_detached_metadata_policy_respects_optional_and_no_prompt_flags():
    base = {"tmdb_id": 123, "imdb_id": 0, "category": "MOVIE"}
    assert should_request_metadata(base, detached=True)
    assert not should_request_metadata({**base, "imdb_optional": True}, detached=True)
    assert not should_request_metadata({**base, "no_prompt_missing_ids": True}, detached=True)
    assert metadata_request({**base, "imdb_optional": True})["missing"] == []


def test_metadata_submission_normalizes_tmdb_and_imdb_ids():
    assert parse_metadata_submission({"tmdb_id": "tv/123", "imdb_id": "tt456"}) == {
        "tmdb_id": 123,
        "imdb_id": 456,
        "category": "TV",
    }


def test_modified_release_detection_allows_discs_and_personal_releases():
    assert detect_modified_release(["/media/Movie {tmdb-123}.mkv"]) == MODIFIED_RELEASE_REASON
    assert detect_modified_release(["/media/Movie {tmdb-123}.mkv"], is_disc=True) is None
    assert detect_modified_release(["/media/Movie {tmdb-123}.mkv"], personal_release=True) is None


def test_redaction_covers_headers_paths_and_query_values():
    value = "Authorization: Bearer secret, Cookie: sid=private; token=hidden https://x.test/announce/abc123456789?api_key=private"
    redacted = Redaction.redact_value(value)
    assert "abc123456789" not in redacted
    assert "private" not in redacted
    assert Redaction.redact_private_info({"Api-Key": "secret"})["Api-Key"] == "[REDACTED]"


def test_safe_url_rejects_private_network_targets():
    async def check() -> None:
        try:
            await assert_public_http_url("http://127.0.0.1/image.jpg")
        except UnsafeURL:
            return
        raise AssertionError("private URL was accepted")

    asyncio.run(check())
