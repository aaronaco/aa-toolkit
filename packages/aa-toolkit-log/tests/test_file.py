"""Saving logs to a file."""

import json

from aa_log import configure_logging, get_logger

TEN_MB = 10 * 1024 * 1024


def messages(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["message"] for line in lines]


def test_no_log_file_is_created_when_no_file_is_set(piped, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_logging()

    get_logger("my_app").info("m")

    assert list(tmp_path.iterdir()) == []


def test_the_file_argument_saves_json_lines_and_the_screen_still_shows_them(piped, tmp_path):
    path = tmp_path / "app.log"
    configure_logging(file=path)

    get_logger("my_app").info("saved")

    assert messages(path) == ["saved"]
    assert [json.loads(line)["message"] for line in piped.getvalue().splitlines()] == ["saved"]


def test_the_file_argument_accepts_a_string(piped, tmp_path):
    path = tmp_path / "app.log"
    configure_logging(file=str(path))

    get_logger("my_app").info("saved")

    assert messages(path) == ["saved"]


def test_a_relative_path_is_relative_to_the_current_folder(piped, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_logging(file="logs/app.log")

    get_logger("my_app").info("saved")

    assert messages(tmp_path / "logs" / "app.log") == ["saved"]


def test_aa_log_file_overrides_the_file_argument(piped, tmp_path, monkeypatch):
    from_env = tmp_path / "env.log"
    from_code = tmp_path / "code.log"
    monkeypatch.setenv("AA_LOG_FILE", str(from_env))
    configure_logging(file=from_code)

    get_logger("my_app").info("saved")

    assert messages(from_env) == ["saved"]
    assert not from_code.exists()


def test_aa_log_file_turns_saving_on_by_itself(piped, tmp_path, monkeypatch):
    path = tmp_path / "env.log"
    monkeypatch.setenv("AA_LOG_FILE", str(path))
    configure_logging()

    get_logger("my_app").info("saved")

    assert messages(path) == ["saved"]


def test_the_file_gets_json_and_the_same_messages_as_a_readable_screen(terminal, tmp_path):
    path = tmp_path / "app.log"
    configure_logging(file=path)
    log = get_logger("my_app")

    log.debug("hidden everywhere")
    log.info("first")
    log.error("second")

    assert messages(path) == ["first", "second"]
    screen = terminal.getvalue()
    assert "first" in screen
    assert "second" in screen
    assert "hidden everywhere" not in screen
    assert not screen.startswith("{")


def test_the_folder_is_created_when_it_does_not_exist(piped, tmp_path):
    path = tmp_path / "not" / "there" / "yet" / "app.log"
    configure_logging(file=path)

    get_logger("my_app").info("saved")

    assert messages(path) == ["saved"]


def test_non_english_characters_and_symbols_are_saved_as_utf_8(piped, tmp_path):
    path = tmp_path / "app.log"
    text = "héllo 日本語 ₱ 🎉"
    configure_logging(file=path)

    get_logger("my_app").info(text)

    assert text.encode("utf-8") in path.read_bytes()
    assert messages(path) == [text]


def test_calling_configure_logging_again_closes_the_first_log_file(piped, tmp_path):
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    configure_logging(file=first)
    get_logger("my_app").info("one")

    configure_logging(file=second)
    get_logger("my_app").info("two")

    assert messages(first) == ["one"]
    assert messages(second) == ["two"]
    first.unlink()  # Windows refuses this while the file is still open
    assert not first.exists()


def test_a_new_file_starts_at_10_mb_and_at_most_3_old_files_are_kept(piped, tmp_path):
    path = tmp_path / "app.log"
    configure_logging(file=path)
    log = get_logger("my_app")
    chunk = "x" * (100 * 1024)

    for _ in range(460):
        log.info(chunk)

    names = sorted(found.name for found in tmp_path.iterdir())
    assert names == ["app.log", "app.log.1", "app.log.2", "app.log.3"]
    for old in ("app.log.1", "app.log.2", "app.log.3"):
        assert TEN_MB - 2 * len(chunk) < (tmp_path / old).stat().st_size <= TEN_MB
