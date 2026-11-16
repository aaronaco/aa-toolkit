"""Lazy imports on Python 3.15 and skipping importlib.metadata when quiet."""

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_aa_and_record_modules(
    tmp_path: Path, *args: str
) -> tuple[subprocess.CompletedProcess[str], set[str]]:
    modules_file = tmp_path / "loaded_modules.txt"
    script = (
        "import sys\n"
        f"sys.argv = ['aa', *{args!r}]\n"
        "from aa_cli.cli import main\n"
        "try:\n"
        "    main()\n"
        "finally:\n"
        f"    open({str(modules_file)!r}, 'w', encoding='utf-8').write("
        "'\\n'.join(sorted(sys.modules)))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    loaded = set(modules_file.read_text(encoding="utf-8").splitlines())
    return proc, loaded


@pytest.mark.skipif(sys.version_info < (3, 15), reason="PEP 810 lazy imports require Python 3.15+")
@pytest.mark.parametrize("args", [("--help",), ("commands", "--json")])
def test_command_without_verbose_does_not_load_importlib_metadata(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    proc, loaded = _run_aa_and_record_modules(tmp_path, *args)

    assert proc.returncode == 0
    assert "importlib.metadata" not in loaded
    assert "email" not in loaded


def test_command_without_verbose_does_not_query_package_version(aa, monkeypatch) -> None:
    calls: list[str] = []
    real_version = importlib.metadata.version

    def spy_version(name: str) -> str:
        calls.append(name)
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", spy_version)

    quiet = aa("commands", "--json")
    assert quiet.exit_code == 0
    assert calls == []

    loud = aa("--verbose", "commands", "--json")
    assert loud.exit_code == 0
    assert calls == ["aa-toolkit-cli"]

    calls.clear()
    ver = aa("--version")
    assert ver.exit_code == 0
    assert calls == ["aa-toolkit-cli"]


def test_verbose_loads_importlib_metadata_and_logs_version(
    tmp_path: Path, package_version: str
) -> None:
    proc, loaded = _run_aa_and_record_modules(tmp_path, "--verbose", "--help")

    assert proc.returncode == 0
    assert "importlib.metadata" in loaded
    assert f"aa {package_version}" in proc.stderr


# typer.main itself imports subprocess at module top level; making Typer's own imports lazy is
# out of scope, so subprocess isolation for our own code is verified separately below.
_UNWANTED_FOR_VERSION = (
    "aa_redact",
    "aa_settings",
    "pydantic",
    "keyring",
    "tomllib",
    "importlib.resources",
    "aa_cli.init",
    "aa_cli.add",
    "aa_cli.redact",
    "aa_cli.secret",
    "aa_cli.commands",
    "aa_cli.crash",
    "aa_cli.git",
    "aa_cli.process",
)


def _any_loaded(loaded: set[str], prefixes: tuple[str, ...]) -> list[str]:
    return sorted(
        mod
        for mod in loaded
        if any(mod == prefix or mod.startswith(f"{prefix}.") for prefix in prefixes)
    )


@pytest.mark.skipif(sys.version_info < (3, 15), reason="PEP 810 lazy imports require Python 3.15+")
@pytest.mark.parametrize(
    ("args", "is_json"),
    [
        (["--version"], False),
        (["--json", "--version"], True),
    ],
    ids=["human", "json"],
)
def test_version_on_python_315_skips_heavy_and_command_modules(
    tmp_path: Path, package_version: str, args: list[str], is_json: bool
) -> None:
    proc, loaded = _run_aa_and_record_modules(tmp_path, *args)

    assert proc.returncode == 0
    assert proc.stderr == ""
    if is_json:
        assert json.loads(proc.stdout) == {"ok": True, "data": {"version": package_version}}
    else:
        assert proc.stdout.strip() == package_version
    assert _any_loaded(loaded, _UNWANTED_FOR_VERSION) == []


@pytest.mark.skipif(sys.version_info < (3, 15), reason="PEP 810 lazy imports require Python 3.15+")
def test_cli_modules_keep_subprocess_and_heavy_imports_lazy_on_import() -> None:
    script = (
        "import sys\n"
        "import aa_cli.add, aa_cli.init, aa_cli.process, aa_cli.redact, aa_cli.secret\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = set(proc.stdout.splitlines())
    assert (
        _any_loaded(
            loaded,
            (
                "subprocess",
                "tomllib",
                "importlib.resources",
                "aa_redact",
                "aa_settings",
                "pydantic",
                "keyring",
            ),
        )
        == []
    )
