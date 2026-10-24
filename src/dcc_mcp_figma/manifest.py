"""Prepare local plugin files from a Figma-assigned ID without installing them."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _assets():
    candidates = (Path(__file__).parent / "plugin", Path(__file__).resolve().parents[2] / "plugin")
    for candidate in candidates:
        if (candidate / "manifest.template.json").is_file():
            return candidate
    raise ValueError("The packaged plugin sources are unavailable.")


def prepare_plugin(plugin_id, bridge_port, output_dir):
    """Write to a new directory; the caller supplies the existing assigned ID.

    Offline validation checks syntax only. It does not prove that Figma has
    assigned this ID or authorize importing the plugin or enabling its network.
    """
    if not isinstance(plugin_id, str) or not re.fullmatch(r"[0-9]{10,30}", plugin_id):
        raise ValueError("Supply the numeric plugin ID assigned by Figma; placeholders are not usable.")
    if type(bridge_port) is not int or not 1024 <= bridge_port <= 65535:
        raise ValueError("Use a loopback bridge port between 1024 and 65535.")
    sources = _assets()
    manifest = json.loads((sources / "manifest.template.json").read_text(encoding="utf-8"))
    manifest["id"] = plugin_id
    manifest["main"] = "code.js"
    manifest["networkAccess"] = {
        "allowedDomains": ["none"],
        "devAllowedDomains": ["http://127.0.0.1:" + str(bridge_port)],
    }
    code = (
        (sources / "runtime.js").read_text(encoding="utf-8")
        + "\n"
        + (sources / "main.js").read_text(encoding="utf-8")
    )
    ui = (sources / "ui.html").read_text(encoding="utf-8")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "code.js").write_text(code, encoding="utf-8")
    (output / "ui.html").write_text(ui, encoding="utf-8")
    return {
        "manifest": str(output / "manifest.json"),
        "plugin_id_verified_by_figma": False,
        "plugin_installed": False,
        "native_acceptance": "not_run",
    }
