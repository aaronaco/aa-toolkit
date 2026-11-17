"""``aa add``: setting up pieces in existing projects with real uv and git."""

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


def uv_machine(machine):
    """A stand-in machine with real uv, real git and a throwaway git identity."""
    machine.add_real("uv")
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    return machine


def host_env(machine) -> dict[str, str]:
    """The real PATH and environment with the stand-in machine's throwaway git identity."""
    return {
        **os.environ,
        **{k: v for k, v in machine.env.items() if k != "PATH" and v is not None},
    }


def make_uv_project(folder: Path, machine) -> Path:
    """Create a plain Python project in ``folder`` with ``uv init``."""
    subprocess.run(
        ["uv", "init"],
        cwd=folder,
        env=host_env(machine),
        check=True,
        capture_output=True,
        text=True,
    )
    return folder


def run_git(cwd: Path, machine, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=host_env(machine),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def req_names(deps: list[str]) -> set[str]:
    """Normalized package names from PEP 508 requirement strings."""
    return {re.split(r"[<>=!~;\[\s]", dep, maxsplit=1)[0].lower() for dep in deps}


CI_FILES = [
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/uv-audit.yml",
    ".github/workflows/zizmor.yml",
]


def test_add_ci_writes_all_four_ci_parts_adds_dev_tools_creates_lockfile_and_leaves_git_alone(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)

    result = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope == {
        "ok": True,
        "data": {
            "piece": "ci",
            "files": [*CI_FILES, "pyproject.toml", "uv.lock"],
            "next_steps": [],
        },
    }
    assert_runs_lint_and_tests_on_windows_and_linux(
        (project / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    dev_deps = pyproject["dependency-groups"]["dev"]
    assert {"ruff", "pytest"} <= req_names(dev_deps)
    assert (project / "uv.lock").is_file()
    assert run_git(project, machine, "diff", "--cached", "--name-only") == ""
    assert run_git(project, machine, "rev-list", "--all", "--count").strip() == "0"


TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "aa_cli" / "templates"
WORKFLOW_TEMPLATES = {
    ".github/workflows/ci.yml": TEMPLATES / "workflows" / "ci.yml",
    ".github/workflows/zizmor.yml": TEMPLATES / "workflows" / "zizmor.yml",
    ".github/workflows/uv-audit.yml": TEMPLATES / "workflows" / "uv-audit.yml",
}
_USES = re.compile(r"^\s*(?:- )?uses: (\S+)(.*)$", re.MULTILINE)


def ready_project(machine, tmp_path) -> Path:
    """A project that already has ruff, pytest and a lockfile, with a fake uv on PATH."""
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[dependency-groups]\ndev = ["ruff", "pytest"]\n',
        encoding="utf-8",
    )
    (project / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return project


@pytest.mark.parametrize("path", sorted(WORKFLOW_TEMPLATES))
def test_add_ci_writes_each_workflow_template_with_every_action_pinned_to_a_commit(
    aa_in, machine, tmp_path, path
):
    project = ready_project(machine, tmp_path)

    result = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    workflow = (project / path).read_text(encoding="utf-8")
    assert workflow == WORKFLOW_TEMPLATES[path].read_text(encoding="utf-8")
    uses = _USES.findall(workflow)
    assert uses
    for action, comment in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}", action), action
        assert re.fullmatch(r" # v\d+\.\d+\.\d+", comment), (action, comment)
    assert checkout_inputs(workflow) == {"persist-credentials": "false"}


def uv_version(workflow: str) -> str:
    [match] = re.finditer(r'^\s+version: "(\d+\.\d+\.\d+)"$', workflow, flags=re.MULTILINE)
    return str(match.group(1))


def runs_on_prs_pushes_to_main_and_weekly(workflow: str) -> bool:
    triggers = workflow.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    return (
        "  push:\n    branches: [main]" in triggers
        and "  pull_request:\n" in triggers
        and "paths" not in triggers
        and re.search(r'  schedule:\n    - cron: "\d+ \d+ \* \* \d"', triggers) is not None
    )


def test_the_zizmor_ci_part_gates_with_annotations_and_no_security_tab_upload(
    aa_in, machine, tmp_path
):
    project = ready_project(machine, tmp_path)

    result = aa_in(project, "add", "ci", "--only", "zizmor", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    workflow = (project / ".github/workflows/zizmor.yml").read_text(encoding="utf-8")
    assert runs_on_prs_pushes_to_main_and_weekly(workflow)
    [step] = [line for line in workflow.splitlines() if "uses: zizmorcore/zizmor-action@" in line]
    after = workflow.split(step, 1)[1]
    assert "advanced-security: false" in after
    assert "annotations: true" in after
    assert "security-events" not in workflow
    assert "continue-on-error" not in workflow


def test_the_audit_ci_part_runs_uv_audit_locked_with_the_tests_parts_uv_version(
    aa_in, machine, tmp_path
):
    project = ready_project(machine, tmp_path)

    result = aa_in(project, "add", "ci", "--only", "audit,tests", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    workflow = (project / ".github/workflows/uv-audit.yml").read_text(encoding="utf-8")
    tests = (project / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert runs_on_prs_pushes_to_main_and_weekly(workflow)
    runs = [line.strip() for line in workflow.splitlines() if line.strip().startswith("- run:")]
    assert len(runs) == 1
    assert runs == ["- run: uv audit --locked --preview-features audit-command"]
    assert "continue-on-error" not in workflow
    assert uv_version(workflow) == uv_version(tests)


def test_the_dependabot_ci_part_updates_actions_monthly_in_one_group_with_a_cooldown(
    aa_in, machine, tmp_path
):
    project = ready_project(machine, tmp_path)

    result = aa_in(project, "add", "ci", "--only", "dependabot", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    config = (project / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert config == (TEMPLATES / "dependabot.yml").read_text(encoding="utf-8")
    assert re.findall(r"package-ecosystem: (\S+)", config) == ["github-actions"]
    assert "interval: monthly" in config
    assert re.search(r"cooldown:\n\s+default-days: 7\n", config)
    assert re.search(r'groups:\n\s+\S+:\n\s+patterns: \["\*"\]', config)
    assert "commit-message" not in config


def checkout_inputs(workflow: str) -> dict[str, str]:
    """The ``with:`` inputs of the workflow's one checkout step."""
    lines = workflow.splitlines()
    [start] = [i for i, line in enumerate(lines) if "uses: actions/checkout@" in line]
    step_indent = len(lines[start]) - len(lines[start].lstrip("- "))
    inputs: dict[str, str] = {}
    in_with = False
    for line in lines[start + 1 :]:
        indent = len(line) - len(line.lstrip())
        if indent < step_indent or line.lstrip().startswith("- "):
            break
        if indent == step_indent:
            in_with = line.strip() == "with:"
        elif in_with:
            key, _, value = line.strip().partition(": ")
            inputs[key] = value
    return inputs


def test_zizmor_finds_nothing_in_the_files_add_ci_writes(aa_in, machine, tmp_path):
    project = ready_project(machine, tmp_path)
    assert aa_in(project, "add", "ci", "--json", env=machine.env).exit_code == 0

    # Offline, with the default persona: the same zizmor run as the commit hook.
    audit = subprocess.run(
        [
            str(Path(sys.executable).with_name("zizmor")),
            "--offline",
            "--no-progress",
            "--strict-collection",
            "--format",
            "json",
            *(str(project / path) for path in CI_FILES),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,  # the exit code is asserted below, with zizmor's output
    )

    assert audit.returncode == 0, audit.stdout + audit.stderr
    assert json.loads(audit.stdout) == []


def assert_runs_lint_and_tests_on_windows_and_linux(workflow: str) -> None:
    assert "push:\n    branches: [main]" in workflow
    assert "pull_request:" in workflow
    assert "os: [ubuntu-latest, windows-latest]" in workflow
    assert re.search(r"astral-sh/setup-uv@[0-9a-f]{40} # v10\.", workflow)
    assert re.search(r"actions/checkout@[0-9a-f]{40} # v\d+\.", workflow)
    assert re.search(r'version: "\d+\.\d+\.\d+"', workflow)
    steps = [line.strip() for line in workflow.splitlines() if line.strip().startswith("- run:")]
    assert steps == [
        "- run: uv python install",
        "- run: uv sync --locked",
        "- run: uv run ruff check .",
        "- run: uv run ruff format --check .",
        "- run: uv run pytest",
    ]


def test_adding_the_tests_part_brings_an_out_of_date_lockfile_up_to_date(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    assert aa_in(project, "add", "ci", "--json", env=machine.env).exit_code == 0
    (project / ".github/workflows/ci.yml").unlink()
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.1.0"', 'version = "0.2.0"'),
        encoding="utf-8",
    )
    lock_check = ["uv", "lock", "--check"]
    stale = subprocess.run(lock_check, cwd=project, env=host_env(machine), capture_output=True)
    assert stale.returncode != 0

    result = aa_in(project, "add", "ci", "--only", "tests", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["files"] == [".github/workflows/ci.yml", "uv.lock"]
    fresh = subprocess.run(lock_check, cwd=project, env=host_env(machine), capture_output=True)
    assert fresh.returncode == 0, fresh.stderr


def test_add_ci_in_a_project_aa_init_just_made_writes_only_the_ci_files(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    init_result = aa_in(tmp_path, "init", "demo", "--json", env=machine.env)
    assert init_result.exit_code == 0, init_result.output
    project = tmp_path / "demo"
    staged_before = run_git(project, machine, "diff", "--cached", "--name-only")
    uv_files = ("pyproject.toml", "uv.lock")
    uv_files_before = {name: (project / name).read_bytes() for name in uv_files}

    # As on a machine with no Python override, so the project's .python-version decides.
    env = {**machine.env, "UV_PYTHON": None}

    result = aa_in(project, "add", "ci", "--json", env=env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["files"] == CI_FILES
    assert {name: (project / name).read_bytes() for name in uv_files} == uv_files_before
    untracked = run_git(project, machine, "ls-files", "--others", "--exclude-standard")
    assert untracked.splitlines() == CI_FILES
    assert run_git(project, machine, "diff", "--cached", "--name-only") == staged_before


def test_add_ci_in_human_mode_lists_the_same_files(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)

    result = aa_in(project, "add", "ci", env=machine.env)

    assert result.exit_code == 0, result.output
    for file_path in (*CI_FILES, "pyproject.toml", "uv.lock"):
        assert file_path in result.stdout


def test_add_ci_keeps_existing_dependency_version_requirements_unchanged(aa_in, machine, tmp_path):
    machine = uv_machine(machine)

    dev_dir = tmp_path / "has-ruff-in-dev"
    dev_dir.mkdir()
    make_uv_project(dev_dir, machine)
    dev_pyproject = dev_dir / "pyproject.toml"
    dev_pyproject.write_text(
        dev_pyproject.read_text(encoding="utf-8")
        + '\n[dependency-groups]\ndev = ["ruff>=0.16,<0.18"]\n',
        encoding="utf-8",
    )

    res_dev = aa_in(dev_dir, "add", "ci", "--json", env=machine.env)
    assert res_dev.exit_code == 0, res_dev.output
    parsed_dev = tomllib.loads(dev_pyproject.read_text(encoding="utf-8"))
    assert "ruff>=0.16,<0.18" in parsed_dev["dependency-groups"]["dev"]
    assert "pytest" in req_names(parsed_dev["dependency-groups"]["dev"])

    deps_dir = tmp_path / "has-pytest-in-deps"
    deps_dir.mkdir()
    make_uv_project(deps_dir, machine)
    deps_pyproject = deps_dir / "pyproject.toml"
    deps_pyproject.write_text(
        deps_pyproject.read_text(encoding="utf-8").replace(
            "dependencies = []", 'dependencies = ["pytest>=8.0,<10"]'
        ),
        encoding="utf-8",
    )

    res_deps = aa_in(deps_dir, "add", "ci", "--json", env=machine.env)
    assert res_deps.exit_code == 0, res_deps.output
    parsed_deps = tomllib.loads(deps_pyproject.read_text(encoding="utf-8"))
    assert parsed_deps["project"]["dependencies"] == ["pytest>=8.0,<10"]
    assert "pytest" not in req_names(parsed_deps["dependency-groups"]["dev"])
    assert "ruff" in req_names(parsed_deps["dependency-groups"]["dev"])

    both_dir = tmp_path / "has-both-unlocked"
    both_dir.mkdir()
    make_uv_project(both_dir, machine)
    both_pyproject = both_dir / "pyproject.toml"
    both_pyproject.write_text(
        both_pyproject.read_text(encoding="utf-8")
        + '\n[dependency-groups]\ndev = ["ruff>=0.16,<0.18", "pytest>=8.0,<10"]\n',
        encoding="utf-8",
    )
    before_bytes = both_pyproject.read_bytes()

    res_both = aa_in(both_dir, "add", "ci", "--json", env=machine.env)
    assert res_both.exit_code == 0, res_both.output
    assert both_pyproject.read_bytes() == before_bytes
    assert (both_dir / "uv.lock").is_file()
    assert json.loads(res_both.stdout)["data"]["files"] == [*CI_FILES, "uv.lock"]

    (both_dir / "uv.lock").unlink()
    res_relock = aa_in(both_dir, "add", "ci", "--json", env=machine.env)
    assert res_relock.exit_code == 0, res_relock.output
    assert (both_dir / "uv.lock").is_file()
    assert json.loads(res_relock.stdout)["data"]["files"] == ["uv.lock"]


def test_add_ci_adds_tools_to_dev_when_only_in_optional_or_non_default_group(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project_dir = tmp_path / "optional-and-non-default"
    project_dir.mkdir()
    project = make_uv_project(project_dir, machine)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + '\n[project.optional-dependencies]\nlint = ["ruff>=0.16,<0.18"]\n'
        + '\n[dependency-groups]\ntest = ["pytest>=8.0,<10"]\n',
        encoding="utf-8",
    )

    result = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dev_deps = parsed["dependency-groups"]["dev"]
    assert {"ruff", "pytest"} <= req_names(dev_deps)
    assert parsed["project"]["optional-dependencies"]["lint"] == ["ruff>=0.16,<0.18"]
    assert parsed["dependency-groups"]["test"] == ["pytest>=8.0,<10"]

    included_dir = tmp_path / "legacy-dev-included"
    included_dir.mkdir()
    make_uv_project(included_dir, machine)
    included_pyproject = included_dir / "pyproject.toml"
    included_pyproject.write_text(
        included_pyproject.read_text(encoding="utf-8")
        + '\n[tool.uv]\ndefault-groups = "all"\ndev-dependencies = ["ruff>=0.16,<0.18"]\n'
        + '\n[dependency-groups]\ntest = [{include-group = "lint"}]\nlint = []\n',
        encoding="utf-8",
    )

    res_included = aa_in(included_dir, "add", "ci", "--json", env=machine.env)

    assert res_included.exit_code == 0, res_included.output
    parsed_included = tomllib.loads(included_pyproject.read_text(encoding="utf-8"))
    assert "ruff>=0.16,<0.18" in parsed_included["tool"]["uv"]["dev-dependencies"]
    assert {"ruff", "pytest"} <= req_names(parsed_included["tool"]["uv"]["dev-dependencies"])

    excluded_dir = tmp_path / "legacy-dev-excluded"
    excluded_dir.mkdir()
    make_uv_project(excluded_dir, machine)
    excluded_pyproject = excluded_dir / "pyproject.toml"
    excluded_pyproject.write_text(
        excluded_pyproject.read_text(encoding="utf-8")
        + '\n[tool.uv]\ndefault-groups = ["test"]\n'
        + 'dev-dependencies = ["ruff>=0.16,<0.18", "pytest>=8.0,<10"]\n'
        + "\n[dependency-groups]\ntest = []\n",
        encoding="utf-8",
    )
    res_excluded = aa_in(excluded_dir, "add", "ci", "--json", env=machine.env)

    assert res_excluded.exit_code == 0, res_excluded.output
    assert json.loads(res_excluded.stdout)["data"]["files"] == [
        *CI_FILES,
        "pyproject.toml",
        "uv.lock",
    ]


def snapshot(project: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }


def test_existing_workflow_with_different_content_fails_with_file_exists_and_changes_nothing(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project_dir = tmp_path / "workflow-file"
    project_dir.mkdir()
    project = make_uv_project(project_dir, machine)
    workflow = project / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: Custom CI\n", encoding="utf-8")
    before = snapshot(project)

    human = aa_in(project, "add", "ci", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert human.exit_code == 1
    assert ".github/workflows/ci.yml" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "file_exists"
    assert ".github/workflows/ci.yml" in error["message"]
    assert error["fix"] == "aa add ci --only zizmor,audit,dependabot"
    assert "aa add ci --only zizmor,audit,dependabot" in human.stderr
    assert snapshot(project) == before
    assert not (project / "uv.lock").exists()

    parent_dir = tmp_path / "parent-file"
    parent_dir.mkdir()
    parent_conflict = make_uv_project(parent_dir, machine)
    (parent_conflict / ".github").write_text("not a dir\n", encoding="utf-8")
    before_parent = snapshot(parent_conflict)

    parent_json = aa_in(parent_conflict, "add", "ci", "--json", env=machine.env)

    assert parent_json.exit_code == 1
    parent_error = json.loads(parent_json.stdout)["error"]
    assert parent_error["code"] == "file_exists"
    assert ".github" in parent_error["message"]
    assert parent_error["fix"] is None
    assert snapshot(parent_conflict) == before_parent
    assert not (parent_conflict / "uv.lock").exists()


def test_when_ci_is_already_there_it_says_so_changes_nothing_and_exits_0(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    first = aa_in(project, "add", "ci", "--json", env=machine.env)
    assert first.exit_code == 0, first.output
    before = snapshot(project)

    human = aa_in(project, "add", "ci", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert human.exit_code == 0, human.output
    assert "already there" in human.stdout.lower()
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout) == {
        "ok": True,
        "data": {"piece": "ci", "files": [], "next_steps": []},
    }
    assert snapshot(project) == before


def test_when_no_pyproject_is_present_it_fails_with_not_a_project(aa, machine, tmp_path):
    machine = uv_machine(machine)

    human = aa("add", "ci", env=machine.env)
    as_json = aa("add", "ci", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "pyproject.toml" in human.stderr
    assert "project's root folder" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "not_a_project"
    assert "project's root folder" in error["fix"]
    assert list(tmp_path.iterdir()) == []


def test_when_uv_fails_it_exits_1_with_step_failed_and_writes_no_workflow(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    project = make_uv_project(tmp_path, machine)
    machine.add_failing("uv", "fake uv: the index is unreachable")

    human = aa_in(project, "add", "ci", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "fake uv: the index is unreachable" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "fake uv: the index is unreachable" in error["message"]
    assert not (project / ".github").exists()


@pytest.mark.parametrize("args", [["add"], ["add", "unknown"]], ids=["missing", "unknown"])
def test_missing_or_unknown_piece_is_a_usage_error_listing_valid_pieces(aa, args):
    human = aa(*args)
    as_json = aa(*args, "--json")

    assert human.exit_code == 2
    assert human.stdout == ""
    assert "ci" in human.stderr
    assert "log" in human.stderr
    assert as_json.exit_code == 2
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "usage"
    assert "ci" in error["message"]
    assert "log" in error["message"]


@pytest.mark.parametrize(
    "only",
    [
        ["--only", "zizmor,audit"],
        ["--only", "zizmor", "--only", "AUDIT"],
        ["--only", " Audit , zizmor"],
    ],
    ids=["commas", "repeated", "spaces-and-case"],
)
def test_only_writes_just_the_chosen_ci_parts_and_leaves_uv_alone(aa_in, machine, tmp_path, only):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    pyproject_before = (project / "pyproject.toml").read_bytes()

    result = aa_in(project, "add", "ci", *only, "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["files"] == [
        ".github/workflows/uv-audit.yml",
        ".github/workflows/zizmor.yml",
    ]
    assert machine.uv_calls() == []
    written = sorted(path.relative_to(project).as_posix() for path in project.rglob("*.yml"))
    assert written == [".github/workflows/uv-audit.yml", ".github/workflows/zizmor.yml"]
    assert (project / "pyproject.toml").read_bytes() == pyproject_before
    assert not (project / "uv.lock").exists()


AUDIT_LOCK_STEP = (
    "Run 'uv lock' and commit uv.lock: the audit workflow runs 'uv audit --locked', which needs it."
)


def test_the_audit_part_without_a_lockfile_says_to_create_one(aa_in, machine, tmp_path):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()

    as_json = aa_in(project, "add", "ci", "--only", "audit", "--json", env=machine.env)
    human = aa_in(project, "add", "ci", "--only", "audit", env=machine.env)

    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout)["data"] == {
        "piece": "ci",
        "files": [".github/workflows/uv-audit.yml"],
        "next_steps": [AUDIT_LOCK_STEP],
    }
    assert human.exit_code == 0, human.output
    assert AUDIT_LOCK_STEP in human.stdout
    assert machine.uv_calls() == []
    assert not (project / "uv.lock").exists()


def test_the_audit_part_with_a_lockfile_has_no_next_steps(aa_in, machine, tmp_path):
    project = ready_project(machine, tmp_path)

    result = aa_in(project, "add", "ci", "--only", "audit", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["next_steps"] == []


def make_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("this user can't create symbolic links")


@pytest.mark.parametrize(
    "link", [".github/workflows/zizmor.yml", ".github"], ids=["file", "parent-folder"]
)
def test_a_dangling_link_where_a_file_goes_is_a_clash(aa_in, machine, tmp_path, link):
    machine.add_real("git")
    (tmp_path / "project").mkdir()
    project = make_uv_project(tmp_path / "project", machine)
    machine.add_fake_uv()
    outside = tmp_path / "outside"
    (project / link).parent.mkdir(parents=True, exist_ok=True)
    make_symlink(project / link, outside)

    result = aa_in(project, "add", "ci", "--only", "zizmor,dependabot", "--json", env=machine.env)

    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "file_exists"
    assert link in error["message"]
    assert not outside.exists()
    assert (project / link).is_symlink()
    assert not (project / ".github/dependabot.yml").exists()


def test_a_file_that_appears_while_aa_writes_is_kept_and_nothing_is_left_written(
    aa_in, machine, tmp_path, monkeypatch
):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    from aa_cli import add

    real_clash = add._clash

    def clash_then_another_program_writes(target: Path, path: str, expected: str) -> str | None:
        found = real_clash(target, path, expected)
        if path == ".github/dependabot.yml":
            (target / path).parent.mkdir(parents=True, exist_ok=True)
            (target / path).write_text("version: 2  # mine\n", encoding="utf-8")
        return found

    monkeypatch.setattr(add, "_clash", clash_then_another_program_writes)

    result = aa_in(project, "add", "ci", "--only", "zizmor,dependabot", "--json", env=machine.env)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "file_exists"
    assert ".github/dependabot.yml" in error["message"]
    dependabot = project / ".github/dependabot.yml"
    assert dependabot.read_text(encoding="utf-8") == "version: 2  # mine\n"
    assert not (project / ".github/workflows/zizmor.yml").exists()


def test_a_failed_write_removes_the_files_this_run_wrote(aa_in, machine, tmp_path, monkeypatch):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    real_open = Path.open

    class DiskFillsUp:
        """A new file that takes a few characters, then runs out of space."""

        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> None:
            self.handle.close()

        def write(self, text: str) -> int:
            self.handle.write(text[:10])
            raise OSError(28, "No space left on device")

    def open_that_fills_the_disk(self, mode="r", *args, **kwargs):
        handle = real_open(self, mode, *args, **kwargs)
        if self.name == "dependabot.yml" and "x" in mode:
            return DiskFillsUp(handle)
        return handle

    monkeypatch.setattr(Path, "open", open_that_fills_the_disk)
    result = aa_in(project, "add", "ci", "--only", "zizmor,dependabot", "--json", env=machine.env)
    monkeypatch.undo()

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "No space left on device" in error["message"]
    assert sorted(path.name for path in project.rglob("*.yml")) == []


def test_a_clash_in_a_chosen_part_writes_nothing_and_the_fix_names_the_others(
    aa_in, machine, tmp_path
):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    zizmor = project / ".github/workflows/zizmor.yml"
    zizmor.parent.mkdir(parents=True)
    zizmor.write_text("name: my zizmor\n", encoding="utf-8")
    before = snapshot(project)

    human = aa_in(project, "add", "ci", "--only", "zizmor,audit", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--only", "zizmor,audit", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "aa add ci --only audit" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "file_exists"
    assert ".github/workflows/zizmor.yml" in error["message"]
    assert error["fix"] == "aa add ci --only audit"
    assert snapshot(project) == before
    assert machine.uv_calls() == []


def test_when_every_chosen_part_clashes_there_is_no_only_fix(aa_in, machine, tmp_path):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    zizmor = project / ".github/workflows/zizmor.yml"
    zizmor.parent.mkdir(parents=True)
    zizmor.write_text("name: my zizmor\n", encoding="utf-8")
    before = snapshot(project)

    as_json = aa_in(project, "add", "ci", "--only", "zizmor", "--json", env=machine.env)

    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "file_exists"
    assert error["fix"] is None
    assert snapshot(project) == before


def test_when_every_chosen_part_is_already_there_it_exits_0_and_changes_nothing(
    aa_in, machine, tmp_path
):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    first = aa_in(project, "add", "ci", "--only", "dependabot,zizmor", "--json", env=machine.env)
    assert first.exit_code == 0, first.output
    before = snapshot(project)

    human = aa_in(project, "add", "ci", "--only", "zizmor", "--only", "dependabot", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--only", "Dependabot", "--json", env=machine.env)

    assert human.exit_code == 0, human.output
    assert "already there" in human.stdout.lower()
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout) == {
        "ok": True,
        "data": {"piece": "ci", "files": [], "next_steps": []},
    }
    assert snapshot(project) == before
    assert machine.uv_calls() == []


def test_an_unknown_ci_part_is_a_usage_error_listing_the_four(aa_in, machine, tmp_path):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    before = snapshot(project)

    human = aa_in(project, "add", "ci", "--only", "zizmor,lint", env=machine.env)
    as_json = aa_in(project, "add", "ci", "--only", "zizmor,lint", "--json", env=machine.env)

    assert human.exit_code == 2
    assert human.stdout == ""
    assert as_json.exit_code == 2
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "usage"
    for message in (human.stderr, error["message"]):
        assert "lint" in message
        assert "tests, zizmor, audit, dependabot" in message
    assert snapshot(project) == before
    assert machine.uv_calls() == []


def test_only_on_add_log_is_a_usage_error_and_changes_nothing(aa_in, machine, tmp_path):
    machine.add_real("git")
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()
    before = snapshot(project)

    human = aa_in(project, "add", "log", "--only", "zizmor", env=machine.env)
    as_json = aa_in(project, "add", "log", "--only", "zizmor", "--json", env=machine.env)

    assert human.exit_code == 2
    assert "--only" in human.stderr
    assert as_json.exit_code == 2
    assert json.loads(as_json.stdout)["error"]["code"] == "usage"
    assert snapshot(project) == before
    assert machine.uv_calls() == []


EXPECTED_LOG_REQUIREMENT = (
    "aa-toolkit-log @ git+https://github.com/aaronaco/aa-toolkit@log-v0.1.0"
    "#subdirectory=packages/aa-toolkit-log"
)


def test_add_log_runs_uv_add_with_pinned_github_requirement_and_leaves_code_and_gitignore_alone(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project_dir = tmp_path / "my-app"
    project_dir.mkdir()
    subprocess.run(
        ["uv", "init", "--package"],
        cwd=project_dir,
        env=host_env(machine),
        check=True,
        capture_output=True,
        text=True,
    )
    gitignore = project_dir / ".gitignore"
    gitignore.write_text("__pycache__/\n.venv/\n", encoding="utf-8")
    before_src = snapshot(project_dir / "src")
    before_gitignore = gitignore.read_bytes()

    machine.add_fake_uv()
    result = aa_in(project_dir, "add", "log", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    calls = machine.uv_calls()
    assert len(calls) == 1
    assert calls[0].cwd == project_dir.resolve()
    assert calls[0].args == ["add", EXPECTED_LOG_REQUIREMENT]
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert data["piece"] == "log"
    assert data["files"] == ["pyproject.toml", "uv.lock"]
    next_steps = data["next_steps"]
    assert isinstance(next_steps, list)
    assert all(isinstance(item, str) for item in next_steps)
    assert len(next_steps) == 2
    assert "from aa_log import configure_logging" in next_steps[0]
    assert "configure_logging()" in next_steps[0]
    assert "only apps" in next_steps[0].lower()
    assert "library" in next_steps[0].lower()
    assert "*.log" in next_steps[1]
    assert "*.log.[1-3]" in next_steps[1]
    assert snapshot(project_dir / "src") == before_src
    assert gitignore.read_bytes() == before_gitignore
    assert run_git(project_dir, machine, "diff", "--cached", "--name-only") == ""
    assert run_git(project_dir, machine, "rev-list", "--all", "--count").strip() == "0"


def test_add_log_in_human_mode_lists_changed_files_and_next_steps(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    machine.add_fake_uv()

    result = aa_in(project, "add", "log", env=machine.env)

    assert result.exit_code == 0, result.output
    for file_path in ("pyproject.toml", "uv.lock"):
        assert file_path in result.stdout
    assert "from aa_log import configure_logging" in result.stdout
    assert "configure_logging()" in result.stdout
    assert "only apps" in result.stdout.lower()
    assert "library" in result.stdout.lower()
    assert "*.log" in result.stdout
    assert "*.log.[1-3]" in result.stdout


def test_add_log_skips_gitignore_step_when_both_lines_are_present_and_shows_only_missing_ones(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)

    both_dir = tmp_path / "both-present"
    both_dir.mkdir()
    make_uv_project(both_dir, machine)
    (both_dir / ".gitignore").write_text(".venv/\n*.log\n*.log.[1-3]\n", encoding="utf-8")

    only_star_dir = tmp_path / "only-star-log"
    only_star_dir.mkdir()
    make_uv_project(only_star_dir, machine)
    (only_star_dir / ".gitignore").write_text("*.log\n", encoding="utf-8")

    only_rotated_dir = tmp_path / "only-rotated"
    only_rotated_dir.mkdir()
    make_uv_project(only_rotated_dir, machine)
    (only_rotated_dir / ".gitignore").write_text("*.log.[1-3]\n", encoding="utf-8")

    commented_dir = tmp_path / "commented"
    commented_dir.mkdir()
    make_uv_project(commented_dir, machine)
    (commented_dir / ".gitignore").write_text("# *.log\n", encoding="utf-8")

    machine.add_fake_uv()

    res_both = aa_in(both_dir, "add", "log", "--json", env=machine.env)
    assert res_both.exit_code == 0, res_both.output
    both_steps = json.loads(res_both.stdout)["data"]["next_steps"]
    assert len(both_steps) == 1
    assert "from aa_log import configure_logging" in both_steps[0]
    assert "configure_logging()" in both_steps[0]
    assert "only apps" in both_steps[0].lower()
    assert "library" in both_steps[0].lower()
    assert ".gitignore" not in both_steps[0]

    human_both = aa_in(both_dir, "add", "log", env=machine.env)
    assert human_both.exit_code == 0, human_both.output
    assert "from aa_log import configure_logging" in human_both.stdout
    assert "configure_logging()" in human_both.stdout
    assert ".gitignore" not in human_both.stdout

    no_gitignore_dir = tmp_path / "no-gitignore"
    no_gitignore_dir.mkdir()
    make_uv_project(no_gitignore_dir, machine)
    gitignore_path = no_gitignore_dir / ".gitignore"
    if gitignore_path.exists():
        gitignore_path.unlink()
    res_no_gitignore = aa_in(no_gitignore_dir, "add", "log", "--json", env=machine.env)
    assert res_no_gitignore.exit_code == 0, res_no_gitignore.output
    assert not gitignore_path.exists()
    no_gi_steps = json.loads(res_no_gitignore.stdout)["data"]["next_steps"]
    assert len(no_gi_steps) == 2
    assert "*.log" in no_gi_steps[1]
    assert "*.log.[1-3]" in no_gi_steps[1]

    res_only_star = aa_in(only_star_dir, "add", "log", "--json", env=machine.env)
    assert res_only_star.exit_code == 0, res_only_star.output
    star_steps = json.loads(res_only_star.stdout)["data"]["next_steps"]
    assert len(star_steps) == 2
    assert star_steps[1] == "Add *.log.[1-3] to .gitignore."

    res_only_rotated = aa_in(only_rotated_dir, "add", "log", "--json", env=machine.env)
    assert res_only_rotated.exit_code == 0, res_only_rotated.output
    rotated_steps = json.loads(res_only_rotated.stdout)["data"]["next_steps"]
    assert len(rotated_steps) == 2
    assert rotated_steps[1] == "Add *.log to .gitignore."

    res_commented = aa_in(commented_dir, "add", "log", "--json", env=machine.env)
    assert res_commented.exit_code == 0, res_commented.output
    commented_steps = json.loads(res_commented.stdout)["data"]["next_steps"]
    assert len(commented_steps) == 2
    assert "*.log" in commented_steps[1]
    assert "*.log.[1-3]" in commented_steps[1]


def test_when_log_is_already_a_dependency_it_says_so_skips_uv_prints_next_steps_and_exits_0(
    aa_in, machine, tmp_path
):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            "dependencies = []",
            f'dependencies = ["{EXPECTED_LOG_REQUIREMENT}"]',
        ),
        encoding="utf-8",
    )
    before = snapshot(project)

    human = aa_in(project, "add", "log", env=machine.env)
    as_json = aa_in(project, "add", "log", "--json", env=machine.env)

    assert human.exit_code == 0, human.output
    assert "already there" in human.stdout.lower()
    assert "from aa_log import configure_logging" in human.stdout
    assert "configure_logging()" in human.stdout
    assert "only apps" in human.stdout.lower()
    assert "*.log" in human.stdout
    assert "*.log.[1-3]" in human.stdout

    assert as_json.exit_code == 0, as_json.output
    envelope = json.loads(as_json.stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["piece"] == "log"
    assert envelope["data"]["files"] == []
    json_steps = envelope["data"]["next_steps"]
    assert len(json_steps) == 2
    assert "from aa_log import configure_logging" in json_steps[0]
    assert "configure_logging()" in json_steps[0]
    assert "only apps" in json_steps[0].lower()
    assert "library" in json_steps[0].lower()
    assert "*.log" in json_steps[1]
    assert "*.log.[1-3]" in json_steps[1]
    assert snapshot(project) == before


def test_add_log_adds_runtime_dependency_when_only_in_dev_group(aa_in, machine, tmp_path):
    machine = uv_machine(machine)
    project = make_uv_project(tmp_path, machine)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + f'\n[dependency-groups]\ndev = ["{EXPECTED_LOG_REQUIREMENT}"]\n',
        encoding="utf-8",
    )
    machine.add_fake_uv()

    result = aa_in(project, "add", "log", "--json", env=machine.env)

    assert result.exit_code == 0, result.output
    assert [call.args for call in machine.uv_calls()] == [["add", EXPECTED_LOG_REQUIREMENT]]
    parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert EXPECTED_LOG_REQUIREMENT in parsed["project"]["dependencies"]


def test_add_log_when_uv_fails_exits_1_with_step_failed(aa_in, machine, tmp_path):
    machine.add_real("git")
    machine.set_identity(name="Ada Lovelace", email="ada@example.com")
    project = make_uv_project(tmp_path, machine)
    before = snapshot(project)
    machine.add_failing("uv", "fake uv: failed to fetch tag log-v0.1.0")

    human = aa_in(project, "add", "log", env=machine.env)
    as_json = aa_in(project, "add", "log", "--json", env=machine.env)

    assert human.exit_code == 1
    assert "fake uv: failed to fetch tag log-v0.1.0" in human.stderr
    assert as_json.exit_code == 1
    error = json.loads(as_json.stdout)["error"]
    assert error["code"] == "step_failed"
    assert "fake uv: failed to fetch tag log-v0.1.0" in error["message"]
    assert snapshot(project) == before
