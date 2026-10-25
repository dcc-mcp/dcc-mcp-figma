"""Built-wheel boundaries: local plugin configuration is never distribution content."""

import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest


def test_wheel_excludes_untracked_local_plugin_configuration(tmp_path):
    pytest.importorskip("build")
    pytest.importorskip("hatchling")
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    for name in ("README.md", "LICENSE", "pyproject.toml"):
        shutil.copyfile(root / name, project / name)
    for name in ("src", "plugin"):
        shutil.copytree(root / name, project / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in (".env", "manifest.json", "pairing.local.json"):
        (project / "plugin" / name).write_text("synthetic-local-data-not-a-credential", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    wheel = next((project / "dist").glob("*.whl"))
    with ZipFile(wheel) as archive:
        plugins = {name for name in archive.namelist() if name.startswith("dcc_mcp_figma/plugin/")}
    assert plugins == {
        "dcc_mcp_figma/plugin/" + name
        for name in ("blueprint.js", "runtime.js", "main.js", "ui.html", "manifest.template.json")
    }
