"""The workspace's own tooling covers the log library, and it installs alone."""

import shlex
import shutil
import subprocess
import tomllib

import pytest


@pytest.fixture
def repo(package_dir):
    return package_dir.parents[1]


@pytest.fixture
def ci(repo):
    return (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_the_test_run_includes_the_log_library(repo):
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))

    assert (
        "packages/aa-toolkit-log/tests" in pyproject["tool"]["pytest"]["ini_options"]["testpaths"]
    )


def test_the_type_check_is_not_limited_to_some_packages(repo):
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))

    assert "src" not in pyproject["tool"]["ty"]


def test_coverage_includes_the_log_library(ci):
    assert "pytest --cov=aa_cli --cov=aa_log --cov-report=xml" in ci


def test_the_analysis_includes_the_log_library(repo):
    settings = (repo / "sonar-project.properties").read_text(encoding="utf-8")

    assert "packages/aa-toolkit-log/src" in settings
    assert "packages/aa-toolkit-log/tests" in settings


def test_ci_runs_a_small_app_with_only_the_log_library_installed(repo, ci):
    commands = [
        line.strip().removeprefix("- run: ")
        for line in ci.splitlines()
        if "--package aa-toolkit-log" in line
    ]
    assert len(commands) == 1
    assert "--locked" in commands[0]
    assert "--isolated" in commands[0]
    uv, *args = shlex.split(commands[0])

    done = subprocess.run(
        [shutil.which(uv) or uv, *args], cwd=repo, capture_output=True, text=True, timeout=300
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"
