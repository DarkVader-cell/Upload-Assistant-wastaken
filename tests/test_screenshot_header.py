import pytest

from src.get_desc import DescriptionBuilder
from src.meta import Meta


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["[h2]Screenshots[/h2]", "[h3]Screenshots[/h3]", "[b]Screenshots[/b]"])
async def test_generic_screenshot_heading_is_suppressed(header: str) -> None:
    builder = DescriptionBuilder(
        "TEST",
        {"DEFAULT": {"screenshot_header": ""}, "TRACKERS": {"TEST": {"screenshot_header": header}}},
    )
    assert await builder.screenshot_header(Meta()) == ""


@pytest.mark.asyncio
async def test_custom_screenshot_heading_is_preserved() -> None:
    builder = DescriptionBuilder(
        "TEST",
        {"DEFAULT": {"screenshot_header": ""}, "TRACKERS": {"TEST": {"screenshot_header": "[h2]Frame Samples[/h2]"}}},
    )
    assert await builder.screenshot_header(Meta()) == "[h2]Frame Samples[/h2]"
