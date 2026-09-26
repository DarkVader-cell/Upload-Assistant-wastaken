from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_APP = ROOT / "web_ui" / "static" / "js" / "config_app.js"


def test_metadata_navigation_includes_all_api_credential_headings() -> None:
    source = CONFIG_APP.read_text(encoding="utf-8")
    metadata_start = source.index('id: "metadata"')
    metadata_end = source.index('const TRACKER_NAVIGATION_GROUPS', metadata_start)
    metadata_group = source[metadata_start:metadata_end]

    assert '"API CREDENTIALS"' in metadata_group
    assert '"METADATA API CREDENTIALS"' in metadata_group


def test_config_content_remounts_when_navigation_group_changes() -> None:
    source = CONFIG_APP.read_text(encoding="utf-8")

    assert 'key={`${activeTab}:${activeSubTab}`}' in source
    assert 'sessionStorage.getItem(`ua_active_subtab:${storedTab}`)' in source


def test_config_subtab_storage_is_scoped_to_the_active_section() -> None:
    source = CONFIG_APP.read_text(encoding="utf-8")

    assert 'sessionStorage.setItem(`ua_active_subtab:${activeTab}`, activeSubTab)' in source
    assert '(storedTab === "default"' in source
