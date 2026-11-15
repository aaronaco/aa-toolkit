"""The code examples in the Settings library's README."""

import json
import os
import re
import subprocess
import sys

import pytest

EXAMPLES = re.compile(
    r"```python\n((?:(?!```).)*?)```\n\n[^\n]+\n\n```(text|json)\n((?:(?!```).)*?)```",
    re.DOTALL,
)

_README_SETTING_VARS = frozenset(
    {
        "DATABASE_URL",
        "PORT",
        "FROM_CODE",
        "FROM_ENV",
        "FROM_DOTENV",
        "FROM_DEFAULT",
        "API_KEY",
        "PIN",
    }
)


def _clean_doc_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.upper() not in _README_SETTING_VARS}


def test_every_example_in_the_readme_prints_what_the_readme_says(
    package_dir, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    readme = (package_dir / "README.md").read_text(encoding="utf-8")
    examples = EXAMPLES.findall(readme)
    assert len(examples) == readme.count("```python") >= 5
    env = _clean_doc_env()

    for code, kind, expected in examples:
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
        )

        assert done.returncode == 0, done.stderr
        if kind == "text":
            assert done.stderr == ""
            assert done.stdout == expected
        else:
            assert done.stdout == ""
            actual_records = [json.loads(line) for line in done.stderr.splitlines()]
            expected_records = [json.loads(line) for line in expected.splitlines()]
            assert len(actual_records) == len(expected_records)
            for actual, exp in zip(actual_records, expected_records, strict=True):
                assert isinstance(actual.pop("time"), str)
                exp.pop("time")
                assert actual == exp


@pytest.mark.parametrize(
    "snippet",
    [
        'uv add "aa-toolkit-settings @ git+https://github.com/aaronaco/aa-toolkit@settings-v0.1.0#subdirectory=packages/aa-toolkit-settings"',
        "get_secret_value()",
        "known_values",
        "secret_values",
        "app_name",
        "aa secret set api_key",
        "Control Panel",
        "Credential Manager",
        "Windows Credentials",
        "2560 bytes",
        "Ed25519",
        "RSA",
        "same Windows user",
        "Only Windows is tested",
        "macOS Keychain",
        "Linux Secret Service",
    ],
)
def test_the_readme_covers_install_secrets_and_limits(package_dir, snippet):
    readme = (package_dir / "README.md").read_text(encoding="utf-8")

    assert snippet in readme


def test_clean_doc_env_strips_readme_setting_vars_case_insensitively(monkeypatch):
    monkeypatch.setenv("port", "9999")
    monkeypatch.setenv("DATABASE_URL", "postgres://ambient")
    monkeypatch.setenv("UNRELATED_ENV_VAR", "keep-me")

    env = _clean_doc_env()

    assert "port" not in env
    assert "DATABASE_URL" not in env
    assert env["UNRELATED_ENV_VAR"] == "keep-me"
