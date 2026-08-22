from web_ui.server import _extract_execution_preview


def test_execution_preview_uses_current_movie_tmdb_artwork_field():
    preview = _extract_execution_preview(
        {
            "category": "MOVIE",
            "title": "Example Movie",
            "tmdb_poster_path": "/movie-poster.jpg",
        },
        "C:/media/Example Movie",
    )

    assert preview["poster_url"] == "https://image.tmdb.org/t/p/w500/movie-poster.jpg"  # noqa: S101


def test_execution_preview_prefers_current_tv_artwork_url():
    preview = _extract_execution_preview(
        {
            "category": "TV",
            "title": "Example Show",
            "artwork_url": "https://images.example/show-poster.jpg",
            "tmdb_poster_path": "/fallback-poster.jpg",
            "poster": "https://legacy.example/poster.jpg",
        },
        "C:/media/Example Show",
    )

    assert preview["poster_url"] == "https://images.example/show-poster.jpg"  # noqa: S101


def test_execution_preview_includes_successful_tracker_uploads():
    preview = _extract_execution_preview(
        {
            "title": "Example Movie",
            "tracker_status": {
                "BLUTOPIA": {
                    "upload_success": True,
                    "upload_name": "Example Movie 2026 1080p WEB-DL",
                    "upload_url": "https://blutopia.cc/torrents/123",
                },
                "AITHER": {
                    "upload_success": False,
                    "upload_name": "A failed upload",
                    "upload_url": "https://aither.cc/torrents/456",
                },
            },
        },
        "/media/Example Movie",
    )

    assert preview["tracker_uploads"] == [  # noqa: S101
        {
            "tracker": "BLUTOPIA",
            "name": "Example Movie 2026 1080p WEB-DL",
            "url": "https://blutopia.cc/torrents/123",
        }
    ]
