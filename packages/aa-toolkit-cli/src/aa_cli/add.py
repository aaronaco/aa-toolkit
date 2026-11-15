"""``aa add``: setting up one piece in an existing project."""

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from aa_cli.init import (
    CI_TEMPLATE,
    CI_WORKFLOW,
    PYPROJECT,
    WRITE_FILES_STEP,
    file_step,
    render,
    step,
    write,
)

UV_LOCK = "uv.lock"
NOT_A_PROJECT_FIX = "Run aa add from the project's root folder (where pyproject.toml is)."
_CI_TOOLS = ("ruff", "pytest")
_REQ_NAME = re.compile(r"\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
_NORMALIZE = re.compile(r"[-_.]+")


class Piece(StrEnum):
    CI = "ci"


class AddError(Exception):
    """Adding a piece cannot proceed because of the target folder or an existing file."""

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.fix = fix


@dataclass(frozen=True)
class Added:
    """What ``add_piece`` changed or wrote in the project."""

    files: list[str]
    next_steps: list[str]


def add_piece(target: Path, piece: Piece) -> Added:
    """Add ``piece`` to the project in ``target``."""
    pyproject = target / PYPROJECT
    if not pyproject.is_file():
        raise AddError("not_a_project", f"{target} has no {PYPROJECT}", fix=NOT_A_PROJECT_FIX)
    return _PIECES[piece](target, pyproject)


def _add_ci(target: Path, pyproject: Path) -> Added:
    workflow = target / CI_WORKFLOW
    expected = render(CI_TEMPLATE)
    workflow_already_there = _check_workflow_path(target, workflow, expected)
    existing = _declared_dependencies(pyproject)
    missing = [tool for tool in _CI_TOOLS if tool not in existing]
    if workflow_already_there and not missing and (target / UV_LOCK).is_file():
        return Added(files=[], next_steps=[])
    before = _read_uv_files(target)
    if missing:
        step("add dev dependencies", target, "uv", "add", "--dev", *missing)
    else:
        step("lock dependencies", target, "uv", "lock")
    changed = [
        name for name, content in _read_uv_files(target).items() if before.get(name) != content
    ]
    if not workflow_already_there:
        with file_step(WRITE_FILES_STEP):
            write(workflow, expected)
        changed.append(CI_WORKFLOW)
    return Added(files=sorted(changed), next_steps=[])


_PIECES = {Piece.CI: _add_ci}


def _check_workflow_path(target: Path, workflow: Path, expected: str) -> bool:
    for parent in (workflow.parent, *workflow.parent.parents):
        if parent == target:
            break
        if parent.exists() and not parent.is_dir():
            rel = parent.relative_to(target).as_posix()
            raise AddError("file_exists", f"{rel} already exists and is not a folder")
    if _has_content(workflow, expected):
        return True
    if workflow.exists():
        raise AddError("file_exists", f"{CI_WORKFLOW} already exists with different content")
    return False


def _has_content(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    try:
        return path.read_text(encoding="utf-8") == expected
    except OSError, UnicodeDecodeError:
        return False


def _declared_dependencies(pyproject: Path) -> set[str]:
    try:
        config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, tomllib.TOMLDecodeError:
        return set()
    project = _as_dict(config.get("project"))
    dep_groups = _as_dict(config.get("dependency-groups"))
    uv_config = _as_dict(_as_dict(config.get("tool")).get("uv"))
    items: list[object] = []
    project_deps = project.get("dependencies", [])
    if isinstance(project_deps, list):
        items.extend(project_deps)
    groups = _groups_with_legacy_dev(dep_groups, uv_config)
    seen: set[str] = set()
    for group_name in _default_group_names(uv_config, groups):
        items.extend(_expand_group(groups, group_name, seen))
    names: set[str] = set()
    for item in items:
        if isinstance(item, str) and (match := _REQ_NAME.match(item)):
            names.add(_NORMALIZE.sub("-", match.group(1)).lower())
    return names


def _groups_with_legacy_dev(
    dep_groups: dict[str, Any], uv_config: dict[str, Any]
) -> dict[str, Any]:
    groups = dict(dep_groups)
    legacy_dev = uv_config.get("dev-dependencies")
    if isinstance(legacy_dev, list):
        dev_group = groups.get("dev")
        existing_dev = dev_group if isinstance(dev_group, list) else []
        groups["dev"] = [*existing_dev, *legacy_dev]
    return groups


def _default_group_names(uv_config: dict[str, Any], dep_groups: dict[str, Any]) -> list[str]:
    default_groups = uv_config.get("default-groups")
    if default_groups is None:
        return ["dev"]
    if default_groups == "all":
        return list(dep_groups)
    if isinstance(default_groups, list):
        return [name for name in default_groups if isinstance(name, str)]
    return []


def _expand_group(dep_groups: dict[str, Any], name: str, seen: set[str]) -> list[object]:
    if name in seen:
        return []
    seen.add(name)
    group = dep_groups.get(name)
    if not isinstance(group, list):
        return []
    expanded: list[object] = []
    for item in group:
        if isinstance(item, dict) and isinstance(inc := item.get("include-group"), str):
            expanded.extend(_expand_group(dep_groups, inc, seen))
        else:
            expanded.append(item)
    return expanded


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    mapping: dict[str, Any] = value
    return mapping


def _read_uv_files(target: Path) -> dict[str, bytes]:
    return {
        name: (target / name).read_bytes()
        for name in (PYPROJECT, UV_LOCK)
        if (target / name).is_file()
    }
