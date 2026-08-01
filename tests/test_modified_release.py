from src.meta import Meta


def test_meta_initializes_modified_release_reason():
    assert Meta().modified_release_reason is None  # noqa: S101

