"""The installed distribution that provides the aa command and the aa_cli import."""

from importlib.metadata import entry_points
from pathlib import Path

import aa_cli


def test_the_aa_command_comes_only_from_aa_toolkit_cli():
    scripts = entry_points(group="console_scripts", name="aa")

    assert [script.dist.name for script in scripts if script.dist] == ["aa-toolkit-cli"]


def test_aa_cli_imports_the_cli_package_from_the_package_folder(package_dir):
    assert Path(aa_cli.__file__).resolve().parent == package_dir / "src" / "aa_cli"
