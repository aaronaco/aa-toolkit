"""The workspace's own tooling covers the redaction library, and it installs alone."""

import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

LIBRARIES = {"aa_log": "aa-toolkit-log", "aa_redact": "aa-toolkit-redact"}


@pytest.fixture
def pyproject(repo):
    return tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture
def ci(repo):
    return (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_the_workspace_installs_the_redaction_library(pyproject):
    assert "aa-toolkit-redact" in pyproject["project"]["dependencies"]
    assert pyproject["tool"]["uv"]["sources"]["aa-toolkit-redact"] == {"workspace": True}


def test_the_test_run_includes_the_redaction_library(pyproject):
    testpaths = pyproject["tool"]["pytest"]["ini_options"]["testpaths"]

    assert "packages/aa-toolkit-redact/tests" in testpaths


def test_the_type_check_is_not_limited_to_some_packages(pyproject):
    assert "src" not in pyproject["tool"]["ty"]


def test_import_sorting_knows_the_redaction_library_is_first_party(pyproject):
    assert "aa_redact" in pyproject["tool"]["ruff"]["lint"]["isort"]["known-first-party"]


def test_coverage_includes_the_redaction_library(ci):
    assert "pytest --cov=aa_cli --cov=aa_log --cov=aa_redact --cov-report=xml" in ci


def test_the_analysis_includes_the_redaction_library(repo):
    settings = (repo / "sonar-project.properties").read_text(encoding="utf-8")

    assert "packages/aa-toolkit-redact/src" in settings
    assert "packages/aa-toolkit-redact/tests" in settings


def test_ci_runs_a_small_app_with_only_the_redaction_library_installed(repo, ci, tmp_path):
    elsewhere = tmp_path / "other-1.0.dist-info"
    elsewhere.mkdir()
    (elsewhere / "METADATA").write_text("Name: other\nVersion: 1.0\n")
    assert "name: Redact library alone" in ci
    commands = [
        line.strip().removeprefix("- run: ")
        for line in ci.splitlines()
        if "--package aa-toolkit-redact" in line
    ]
    assert len(commands) == 1
    assert "--locked" in commands[0]
    assert "--isolated" in commands[0]
    uv, *args = shlex.split(commands[0])

    done = subprocess.run(
        [shutil.which(uv) or uv, *args],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


@pytest.fixture
def contract_command(repo, ci):
    """The import contract command, taken from the hook that CI runs."""
    hooks = tomllib.loads((repo / "prek.toml").read_text(encoding="utf-8"))
    entries = [
        hook["entry"]
        for group in hooks["repos"]
        for hook in group["hooks"]
        if hook["id"] == "import-linter"
    ]
    assert len(entries) == 1
    assert "uv run --locked prek run --all-files" in ci
    return shlex.split(entries[0])


def test_the_import_contract_passes_on_the_libraries_as_they_are(repo, contract_command):
    uv, *args = contract_command

    done = subprocess.run(
        [shutil.which(uv) or uv, *args], cwd=repo, capture_output=True, text=True, timeout=300
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "Libraries don't import each other KEPT" in done.stdout


def test_the_import_contract_covers_every_library_and_only_libraries(repo, pyproject):
    settings = pyproject["tool"]["importlinter"]
    libraries = sorted(
        package.name
        for package in repo.glob("packages/*/src/*")
        if package.is_dir() and package.name != "aa_cli"
    )

    assert libraries == sorted(LIBRARIES)
    assert sorted(settings["root_packages"]) == libraries
    assert [sorted(contract["modules"]) for contract in settings["contracts"]] == [libraries]


@pytest.mark.parametrize(
    ("importer", "imported"), [("aa_log", "aa_redact"), ("aa_redact", "aa_log")]
)
def test_the_import_contract_fails_when_one_library_imports_another(
    repo, contract_command, tmp_path, importer, imported
):
    for package, folder in LIBRARIES.items():
        shutil.copytree(repo / "packages" / folder / "src" / package, tmp_path / package)
    shutil.copy(repo / "pyproject.toml", tmp_path)
    with (tmp_path / importer / "__init__.py").open("a", encoding="utf-8") as source:
        source.write(f"\nimport {imported}\n")
    lint_imports = shutil.which(contract_command[-1], path=Path(sys.executable).parent)
    assert lint_imports

    done = subprocess.run(
        [lint_imports],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert done.returncode == 1, done.stdout + done.stderr
    assert "Libraries don't import each other BROKEN" in done.stdout
    assert f"{importer} is not allowed to import {imported}" in done.stdout
