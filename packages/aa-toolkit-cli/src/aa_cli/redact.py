"""``aa redact``: cleaning a file or piped text with the redaction library."""

import contextlib
import re
import sys
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from pathlib import Path
from typing import BinaryIO

from aa_redact import Finding, Redactor, ip_address, phone_number

type Detector = Callable[[str], Iterable[Finding]]

WITH_DETECTORS: dict[str, Detector] = {
    "IP_ADDRESS": ip_address,
    "PHONE": phone_number,
}
WITH_KINDS: tuple[str, ...] = tuple(WITH_DETECTORS)
WITHOUT_KINDS: tuple[str, ...] = (
    "AWS_ACCESS_KEY",
    "GITHUB_TOKEN",
    "API_KEY",
    "SLACK_TOKEN",
    "JWT",
    "BEARER_TOKEN",
    "PRIVATE_KEY",
    "URL_PASSWORD",
    "EMAIL",
    "CARD",
)


class UnknownKind(Exception):
    """A kind name passed to ``--with`` or ``--without`` is not accepted by that flag."""

    def __init__(self, flag: str, kind: str, allowed: Sequence[str]) -> None:
        accepted = ", ".join(allowed)
        super().__init__(f"unknown kind {kind!r}; choose from: {accepted}")
        self.flag = flag


class FileError(Exception):
    """The input file does not exist, is a folder, or cannot be read."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DetectorFailed(Exception):
    """A Detector raised while cleaning text; the message never holds the input text."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(f"detector failed ({type(exc).__name__})")


def _parse_kinds(flag: str, values: Sequence[str], allowed: Sequence[str]) -> list[str]:
    parsed: list[str] = []
    for entry in values:
        for raw in entry.split(","):
            name = raw.strip()
            kind = name.upper()
            if kind not in allowed:
                raise UnknownKind(flag, name, allowed)
            parsed.append(kind)
    return parsed


def build_redactor(with_values: Sequence[str] = (), without_values: Sequence[str] = ()) -> Redactor:
    with_kinds = _parse_kinds("--with", with_values, WITH_KINDS)
    without_kinds = _parse_kinds("--without", without_values, WITHOUT_KINDS)
    detectors = [WITH_DETECTORS[kind] for kind in dict.fromkeys(with_kinds)]
    return Redactor(detectors=detectors, without=without_kinds, max_length=sys.maxsize)


_KEY_LABEL = r"(?:[A-Z0-9]{1,20} ){0,4}PRIVATE KEY(?: BLOCK)?-----"
_KEY_START = re.compile(rf"-----BEGIN {_KEY_LABEL}")
_KEY_END = re.compile(rf"-----END {_KEY_LABEL}")


def _has_unclosed_key(text: str) -> bool:
    starts = list(_KEY_START.finditer(text))
    return bool(starts) and _KEY_END.search(text, starts[-1].end()) is None


@contextlib.contextmanager
def open_input(file: Path | None) -> Generator[BinaryIO]:
    if file is None:
        yield sys.stdin.buffer
        return
    if file.is_dir():
        raise FileError("cannot_read", f"{file} is a folder")
    try:
        stream = file.open("rb")
    except FileNotFoundError as exc:
        raise FileError("file_not_found", f"{file} does not exist") from exc
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise FileError("cannot_read", f"cannot read {file}: {detail}") from exc
    with stream:
        yield stream


def _clean(redact: Redactor, text: str) -> str:
    try:
        return redact(text)
    except Exception as exc:
        raise DetectorFailed(exc) from None


def _find(redact: Redactor, text: str) -> list[Finding]:
    try:
        return redact.find(text)
    except Exception as exc:
        raise DetectorFailed(exc) from None


def _read_chunks(stream: BinaryIO) -> Iterator[tuple[int, str]]:
    held: list[str] = []
    first_line = 1
    line_no = 0
    while raw := stream.readline():
        line_no += 1
        line = raw.decode("utf-8", errors="surrogateescape")
        if not held and not _has_unclosed_key(line):
            yield line_no, line
            continue
        if not held:
            first_line = line_no
        held.append(line)
        if _KEY_END.search(line) and not _has_unclosed_key(line):
            yield first_line, "".join(held)
            held.clear()
    if held:
        yield first_line, "".join(held)


def clean_stream(stream: BinaryIO, redact: Redactor) -> Iterator[str]:
    for _, chunk in _read_chunks(stream):
        yield _clean(redact, chunk)


def _position(text: str, offset: int, first_line: int) -> tuple[int, int]:
    prefix = text[:offset]
    return first_line + prefix.count("\n"), offset - prefix.rfind("\n")


def find_stream(stream: BinaryIO, redact: Redactor) -> Iterator[dict[str, int | str]]:
    for first_line, chunk in _read_chunks(stream):
        for finding in _find(redact, chunk):
            line, column = _position(chunk, finding.start, first_line)
            end_line, end_column = _position(chunk, finding.end, first_line)
            yield {
                "line": line,
                "column": column,
                "end_line": end_line,
                "end_column": end_column,
                "kind": finding.kind,
            }


def find_all(file: Path | None, redact: Redactor) -> list[dict[str, int | str]]:
    with open_input(file) as stream:
        return list(find_stream(stream, redact))


def check_file(file: Path | None, redact: Redactor) -> bool:
    source = str(file) if file is not None else "<stdin>"
    found = False
    with open_input(file) as stream:
        for item in find_stream(stream, redact):
            found = True
            sys.stdout.write(f"{source}:{item['line']}:{item['column']}: {item['kind']}\n")
            sys.stdout.flush()
    return found


def _as_text(chunk: str) -> str:
    return chunk.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")


def _write_chunk(chunk: str) -> None:
    if sys.stdout.isatty():
        sys.stdout.write(_as_text(chunk))
        sys.stdout.flush()
    else:
        sys.stdout.flush()
        sys.stdout.buffer.write(chunk.encode("utf-8", errors="surrogateescape"))
        sys.stdout.buffer.flush()


def clean_text(file: Path | None, redact: Redactor) -> str:
    with open_input(file) as stream:
        return _as_text("".join(clean_stream(stream, redact)))


def redact_file(file: Path | None, redact: Redactor) -> None:
    with open_input(file) as stream:
        for chunk in clean_stream(stream, redact):
            _write_chunk(chunk)
