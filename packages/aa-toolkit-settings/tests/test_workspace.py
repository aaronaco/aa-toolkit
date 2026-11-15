"""The workspace's own tooling covers the Settings library, and it installs alone."""

import os
import shlex
import shutil
import subprocess
import tomllib

import pytest


@pytest.fixture
def pyproject(repo):
    return tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture
def ci(repo):
    return (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_the_workspace_installs_the_settings_library(pyproject):
    assert "aa-toolkit-settings" in pyproject["project"]["dependencies"]
    assert pyproject["tool"]["uv"]["sources"]["aa-toolkit-settings"] == {"workspace": True}


def test_the_test_run_includes_the_settings_library(pyproject):
    testpaths = pyproject["tool"]["pytest"]["ini_options"]["testpaths"]

    assert "packages/aa-toolkit-settings/tests" in testpaths


def test_import_sorting_knows_the_settings_library_is_first_party(pyproject):
    assert "aa_settings" in pyproject["tool"]["ruff"]["lint"]["isort"]["known-first-party"]


def test_coverage_includes_the_settings_library(ci):
    assert (
        "pytest --cov=aa_cli --cov=aa_log --cov=aa_redact --cov=aa_settings --cov-report=xml"
        in ci
    )


def test_the_analysis_includes_the_settings_library(repo):
    settings = (repo / "sonar-project.properties").read_text(encoding="utf-8")

    assert "packages/aa-toolkit-settings/src" in settings
    assert "packages/aa-toolkit-settings/tests" in settings


def test_dependency_review_allows_typing_extensions_by_name(repo):
    policy = (repo / ".github" / "dependency-review.yml").read_text(encoding="utf-8")

    assert "allow-dependencies-licenses:" in policy
    assert "pkg:pypi/typing-extensions" in policy


def test_ci_runs_a_small_app_with_only_the_settings_library_installed(repo, ci, tmp_path):
    elsewhere = tmp_path / "other-1.0.dist-info"
    elsewhere.mkdir()
    (elsewhere / "METADATA").write_text("Name: other\nVersion: 1.0\n")
    assert "name: Settings library alone" in ci
    commands = [
        line.strip().removeprefix("- run: ")
        for line in ci.splitlines()
        if "--package aa-toolkit-settings" in line
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
