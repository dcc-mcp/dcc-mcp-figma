"""Source-only preparation contracts; fixture IDs establish no Figma authority."""

import json

import pytest

from dcc_mcp_figma.manifest import prepare_plugin


def test_preparation_is_local_explicit_and_does_not_replace_files(tmp_path):
    # This synthetic numeric identifier is not an assigned or installed plugin.
    output = tmp_path / "prepared"
    result = prepare_plugin("1234567890123456", 19061, output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "1234567890123456"
    assert manifest["documentAccess"] == "dynamic-page"
    assert manifest["editorType"] == ["figma"]
    assert manifest["networkAccess"] == {
        "allowedDomains": ["none"],
        "devAllowedDomains": ["http://127.0.0.1:19061"],
    }
    assert not manifest.get("permissions")
    assert result["plugin_installed"] is False
    assert result["plugin_id_verified_by_figma"] is False
    assert (output / "code.js").is_file()
    with pytest.raises(FileExistsError):
        prepare_plugin("1234567890123456", 19061, output)


@pytest.mark.parametrize("plugin_id", [None, "__FIGMA_ASSIGNED_ID__", "", "123", "secret/token"])
def test_invalid_id_does_not_create_files(plugin_id, tmp_path):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        prepare_plugin(plugin_id, 19061, output)
    assert not output.exists()
