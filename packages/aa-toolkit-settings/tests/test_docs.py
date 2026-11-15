"""The code examples in the Settings library's README."""

import json
import re
import subprocess
import sys

import pytest

EXAMPLES = re.compile(
    r"```python\n((?:(?!```).)*?)```\n\n[^\n]+\n\n```(text|json)\n((?:(?!```).)*?)```",
    re.DOTALL,
)


def test_every_example_in_the_readme_prints_what_the_readme_says(package_dir, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    readme = (package_dir / "README.md").read_text(encoding="utf-8")
    examples = EXAMPLES.findall(readme)
    assert len(examples) == readme.count("```python") >= 5

    for code, kind, expected in examples:
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

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
    ],
)
def test_the_readme_covers_install_secrets_and_limits(package_dir, snippet):
    readme = (package_dir / "README.md").read_text(encoding="utf-8")

    assert snippet in readme
