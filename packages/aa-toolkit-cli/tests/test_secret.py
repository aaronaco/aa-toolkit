"""``aa secret set`` and ``aa secret delete``: Secrets in the Secret store."""

import json
from pathlib import Path

import click
import keyring
import pytest
import typer
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import KeyringError, PasswordDeleteError

from aa_settings import BaseSettings, Secret, SettingsConfigDict

VALUE = "sk-live-abc123"


class _MemoryKeyring(KeyringBackend):
    """In-memory keyring backend, so no test touches the machine's Secret store."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.entries:
            raise PasswordDeleteError(f"{service}:{username}")
        del self.entries[(service, username)]


class _BrokenKeyring(_MemoryKeyring):
    """A Secret store that is there but fails on every write."""

    def set_password(self, service: str, username: str, password: str) -> None:
        raise KeyringError(f"cannot write {password}")


@pytest.fixture
def store():
    previous = keyring.get_keyring()
    backend = _MemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The current folder holds a project named my-app."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-app"\n', encoding="utf-8")
    return tmp_path


def assert_value_hidden(result, value: str = VALUE) -> None:
    assert value not in result.stdout
    assert value not in result.stderr


def test_set_saves_the_typed_value_for_the_project_and_settings_reads_it(aa, store, project):
    result = aa("secret", "set", "api_key", typed=VALUE)

    assert result.exit_code == 0, result.output
    assert "Saved api_key for my-app in the Secret store." in result.stdout
    assert store.entries == {("my-app", "api_key"): VALUE}

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(app_name="my-app", env_file=None)

        api_key: Secret[str]

    assert Settings().api_key.get_secret_value() == VALUE
    assert_value_hidden(result)


def test_set_prompts_once_with_the_field_name(aa, store, project):
    result = aa("secret", "set", "api_key", typed=VALUE)

    assert result.exit_code == 0, result.output
    assert result.output.count("Value for api_key: ") == 1


@pytest.mark.parametrize("ending", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_set_removes_one_trailing_line_ending_from_piped_input(aa, store, project, ending):
    result = aa("secret", "set", "api_key", stdin=f"{VALUE}{ending}".encode())

    assert result.exit_code == 0, result.output
    assert store.entries == {("my-app", "api_key"): VALUE}
    assert "Value for" not in result.output
    assert_value_hidden(result)


def test_set_removes_only_one_trailing_line_ending(aa, store, project):
    result = aa("secret", "set", "api_key", stdin=f"{VALUE}\n\n".encode())

    assert result.exit_code == 0, result.output
    assert store.entries == {("my-app", "api_key"): f"{VALUE}\n"}


def test_set_with_app_saves_for_that_app_without_a_pyproject(aa, store):
    result = aa("secret", "set", "api_key", "--app", "other", stdin=VALUE)

    assert result.exit_code == 0, result.output
    assert "Saved api_key for other in the Secret store." in result.stdout
    assert store.entries == {("other", "api_key"): VALUE}


def test_set_with_app_wins_over_the_pyproject_name(aa, store, project):
    result = aa("secret", "set", "api_key", "--app", "other", stdin=VALUE)

    assert result.exit_code == 0, result.output
    assert store.entries == {("other", "api_key"): VALUE}


@pytest.mark.parametrize(
    "pyproject",
    [None, '[tool.ruff]\nline-length = 100\n', "not = [toml", '[project]\nname = ""\n'],
    ids=["missing", "no-project-name", "broken", "empty-name"],
)
@pytest.mark.parametrize("command", ["set", "delete"])
def test_no_app_name_is_a_usage_error_naming_app(aa, store, tmp_path, pyproject, command):
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")

    result = aa("--json", "secret", command, "api_key", stdin=VALUE)

    assert result.exit_code == 2, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "usage"
    assert "--app" in error["message"]
    assert store.entries == {}


def test_no_app_name_in_human_mode_names_app_on_stderr(aa, store):
    result = aa("secret", "set", "api_key", stdin=VALUE)

    assert result.exit_code == 2
    assert "--app" in result.stderr


@pytest.mark.parametrize("name", ["api-key", "1key", "class", "api key"])
@pytest.mark.parametrize("command", ["set", "delete"])
def test_a_name_that_is_not_a_python_identifier_is_a_usage_error(
    aa, store, project, name, command
):
    store.entries[("my-app", name)] = "kept"

    result = aa("--json", "secret", command, name, stdin=VALUE)

    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["error"]["code"] == "usage"
    assert store.entries == {("my-app", name): "kept"}


@pytest.mark.parametrize(
    "how", [{"typed": ""}, {"stdin": b""}, {"stdin": b"\n"}], ids=["typed", "piped", "newline"]
)
def test_an_empty_value_is_a_usage_error_and_nothing_is_saved(aa, store, project, how):
    store.entries[("my-app", "api_key")] = "kept"

    result = aa("secret", "set", "api_key", **how)

    assert result.exit_code == 2, result.output
    assert "empty" in result.stderr
    assert store.entries == {("my-app", "api_key"): "kept"}


def test_a_value_over_the_limit_is_secret_too_large_with_its_size_and_the_limit(
    aa, store, project
):
    big = "x" * 1281  # 2562 bytes in UTF-16

    result = aa("--json", "secret", "set", "api_key", stdin=big)

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "secret_too_large"
    assert "2562" in error["message"]
    assert "2560" in error["message"]
    assert store.entries == {}
    assert_value_hidden(result, big)


def test_a_value_at_the_limit_is_saved(aa, store, project):
    result = aa("secret", "set", "api_key", stdin="x" * 1280)

    assert result.exit_code == 0, result.output
    assert store.entries == {("my-app", "api_key"): "x" * 1280}


def test_set_replaces_an_existing_secret_and_says_replaced(aa, store, project):
    store.entries[("my-app", "api_key")] = "old"

    result = aa("secret", "set", "api_key", stdin=VALUE)

    assert result.exit_code == 0, result.output
    assert "Replaced api_key for my-app in the Secret store." in result.stdout
    assert store.entries == {("my-app", "api_key"): VALUE}


@pytest.mark.parametrize(
    ("args", "env"),
    [(["--json", "secret", "set"], None), (["secret", "set"], {"AA_JSON": "1"})],
    ids=["flag", "env"],
)
@pytest.mark.parametrize("existing", [False, True], ids=["new", "replaced"])
def test_set_in_json_mode_prints_app_name_and_replaced(aa, store, project, args, env, existing):
    if existing:
        store.entries[("my-app", "api_key")] = "old"

    result = aa(*args, "api_key", stdin=f"{VALUE}\n", env=env)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "ok": True,
        "data": {"app": "my-app", "name": "api_key", "replaced": existing},
    }
    assert_value_hidden(result)


def test_json_flag_after_the_group_name_works(aa, store, project):
    result = aa("secret", "--json", "set", "api_key", stdin=VALUE)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["replaced"] is False


@pytest.mark.parametrize(
    ("args", "env"),
    [(["--json"], None), ([], {"AA_JSON": "1"})],
    ids=["flag", "env"],
)
def test_set_in_json_mode_with_a_terminal_is_a_usage_error_without_prompting(
    aa, store, project, args, env
):
    result = aa(*args, "secret", "set", "api_key", typed=VALUE, env=env)

    assert result.exit_code == 2, result.output
    envelope = json.loads(result.stdout)
    assert envelope["error"]["code"] == "usage"
    assert "Value for" not in result.output
    assert store.entries == {}


def test_ctrl_c_at_the_prompt_is_aborted(aa, store, project, monkeypatch):
    def press_ctrl_c(*args, **kwargs):
        raise click.exceptions.Abort()  # what click raises on Ctrl+C at a prompt

    monkeypatch.setattr(typer, "prompt", press_ctrl_c)

    result = aa("secret", "set", "api_key")

    assert result.exit_code == 130, result.output
    assert "Aborted" in result.stderr
    assert store.entries == {}


def test_delete_removes_the_saved_secret(aa, store, project):
    store.entries[("my-app", "api_key")] = VALUE
    store.entries[("my-app", "other")] = "kept"

    result = aa("secret", "delete", "api_key")

    assert result.exit_code == 0, result.output
    assert result.stdout == "Deleted api_key for my-app from the Secret store.\n"
    assert store.entries == {("my-app", "other"): "kept"}
    assert_value_hidden(result)


def test_delete_with_app_removes_that_apps_secret(aa, store):
    store.entries[("other", "api_key")] = VALUE

    result = aa("--json", "secret", "delete", "api_key", "--app", "other")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"ok": True, "data": {"app": "other", "name": "api_key"}}
    assert store.entries == {}


def test_delete_in_json_mode_with_aa_json_prints_app_and_name(aa, store, project):
    store.entries[("my-app", "api_key")] = VALUE

    result = aa("secret", "delete", "api_key", env={"AA_JSON": "1"})

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"ok": True, "data": {"app": "my-app", "name": "api_key"}}
    assert_value_hidden(result)


def test_delete_of_a_secret_that_is_not_saved_is_secret_not_found(aa, store, project):
    store.entries[("my-app", "other")] = "kept"

    result = aa("--json", "secret", "delete", "api_key")

    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "secret_not_found"
    assert "api_key" in error["message"]
    assert "my-app" in error["message"]
    assert store.entries == {("my-app", "other"): "kept"}


@pytest.mark.parametrize(
    "args", [["set", "api_key"], ["delete", "api_key"]], ids=["set", "delete"]
)
def test_no_secret_store_is_no_secret_store(aa, project, args):
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        result = aa("--json", "secret", *args, stdin=VALUE)
    finally:
        keyring.set_keyring(previous)

    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error"]["code"] == "no_secret_store"
    assert_value_hidden(result)


def test_no_secret_store_in_human_mode_says_so_on_stderr(aa, project):
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        result = aa("secret", "delete", "api_key")
    finally:
        keyring.set_keyring(previous)

    assert result.exit_code == 1
    assert "No Secret store" in result.stderr


def test_a_secret_store_that_fails_is_unexpected_without_the_value(aa, project):
    previous = keyring.get_keyring()
    keyring.set_keyring(_BrokenKeyring())
    try:
        result = aa("--json", "secret", "set", "api_key", stdin=VALUE)
    finally:
        keyring.set_keyring(previous)

    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout)["error"]["code"] == "unexpected"
    assert_value_hidden(result)


def test_piped_input_that_is_not_utf8_is_a_usage_error_without_the_value(aa, store, project):
    result = aa("--json", "secret", "set", "api_key", stdin=b"caf\xe9-secret")

    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["error"]["code"] == "usage"
    assert "caf" not in result.stdout
    assert store.entries == {}


def test_secret_help_shows_set_and_delete(aa):
    result = aa("secret", "--help")

    assert result.exit_code == 0, result.output
    assert "set" in result.stdout
    assert "delete" in result.stdout


def test_the_value_is_never_an_argument(aa, store, project):
    result = aa("secret", "set", "api_key", VALUE)

    assert result.exit_code == 2
    assert store.entries == {}
