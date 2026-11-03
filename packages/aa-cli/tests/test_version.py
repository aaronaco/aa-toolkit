import json

import pytest


def test_version_prints_the_package_version(aa, package_version):
    result = aa("--version")

    assert result.exit_code == 0
    assert result.stdout.strip() == package_version


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--json", "--version"], None),
        (["--version"], {"AA_JSON": "1"}),
    ],
    ids=["flag", "env"],
)
def test_version_in_json_mode_is_one_envelope(aa, package_version, args, env):
    result = aa(*args, env=env)

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"ok": True, "data": {"version": package_version}}
