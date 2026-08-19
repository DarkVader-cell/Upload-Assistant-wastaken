from data.example_config import config as example_config
from src.args import Args
from src.meta import Meta


def test_force_upload_flag_is_parsed() -> None:
    meta, _parser, _before_args = Args(example_config).parse([".", "--force-upload"], Meta())

    assert meta.force_upload is True  # noqa: S101
