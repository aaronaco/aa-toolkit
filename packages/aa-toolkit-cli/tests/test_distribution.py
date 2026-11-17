"""The installed distribution that provides the aa command and the aa_cli import."""

import subprocess
import tarfile
import zipfile
from importlib.metadata import entry_points
from pathlib import Path

import aa_cli


def test_the_aa_command_comes_only_from_aa_toolkit_cli():
    scripts = entry_points(group="console_scripts", name="aa")

    assert [script.dist.name for script in scripts if script.dist] == ["aa-toolkit-cli"]


def test_aa_cli_imports_the_cli_package_from_the_package_folder(package_dir):
    assert Path(aa_cli.__file__).resolve().parent == package_dir / "src" / "aa_cli"


def test_the_built_package_contains_the_workflow_template(package_dir, tmp_path):
    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--sdist", "--out-dir", str(out)],
        cwd=package_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    [wheel] = out.glob("*.whl")
    [sdist] = out.glob("*.tar.gz")
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    with tarfile.open(sdist) as archive:
        sdist_names = [name.partition("/")[2] for name in archive.getnames()]

    assert "aa_cli/templates/workflows/ci.yml" in wheel_names
    assert "src/aa_cli/templates/workflows/ci.yml" in sdist_names
