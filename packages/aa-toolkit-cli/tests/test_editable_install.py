"""The editable uv tool install described in the README, run for real."""

import os
import shutil
import subprocess
import sys


def test_editable_tool_install_runs_aa_and_picks_up_source_edits(
    tmp_path, package_dir, package_version
):
    # Install a copy, so editing the source below never touches the checkout.
    source = tmp_path / "aa-toolkit-cli"
    shutil.copytree(package_dir, source, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    bin_dir = tmp_path / "bin"
    env = {**os.environ, "UV_TOOL_DIR": str(tmp_path / "tools"), "UV_TOOL_BIN_DIR": str(bin_dir)}
    python = f"{sys.version_info.major}.{sys.version_info.minor}"

    subprocess.run(
        ["uv", "tool", "install", "--editable", str(source), "--python", python],
        env=env,
        check=True,
        capture_output=True,
    )
    aa = shutil.which("aa", path=str(bin_dir))
    assert aa is not None

    before = subprocess.run([aa, "--version"], env=env, capture_output=True, text=True)
    assert before.returncode == 0
    assert before.stdout.strip() == package_version

    init = source / "src" / "aa_cli" / "__init__.py"
    init.write_text(
        init.read_text() + '\nimport sys\n\nprint("edited source is live", file=sys.stderr)\n'
    )

    after = subprocess.run([aa, "--version"], env=env, capture_output=True, text=True)
    assert after.returncode == 0
    assert "edited source is live" in after.stderr
