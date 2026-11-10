"""Walking any value, finding what's sensitive in it and replacing that with Placeholders."""

from collections.abc import Iterable
from numbers import Number
from typing import overload

from aa_redact._detectors import BUILT_IN
from aa_redact._finding import Detector, Finding
from aa_redact._names import HIDDEN_KIND, SensitiveNames

_HIDDEN = f"[{HIDDEN_KIND}]"
_MAX_DEPTH = 32  # far past real data, and well inside Python's recursion limit
_SHAPES = (list, tuple, set, frozenset)


def _find(text: str, detectors: Iterable[Detector]) -> list[Finding]:
    """Return what the Detectors found, in text order, with overlaps merged into one Finding."""
    found: list[tuple[Finding, int]] = []
    for detector_order, detector in enumerate(detectors):
        for finding in detector(text):
            if not 0 <= finding.start < finding.end <= len(text):
                raise ValueError(
                    f"a Detector returned a Finding that doesn't fit the text: {finding}"
                )
            found.append((finding, detector_order))
    return _merge(found)


def _merge(found: list[tuple[Finding, int]]) -> list[Finding]:
    """Merge overlapping Findings. The longest names the kind, then the earlier Detector."""
    merged: list[Finding] = []
    naming_rank = (0, 0)  # the rank of the Finding that gave the last merged one its kind
    for finding, detector_order in sorted(found, key=lambda pair: pair[0].start):
        rank = (finding.end - finding.start, -detector_order)
        if merged and finding.start < merged[-1].end:
            last = merged[-1]
            kind = finding.kind if rank > naming_rank else last.kind
            merged[-1] = Finding(kind, last.start, max(last.end, finding.end))
            naming_rank = max(naming_rank, rank)
        else:
            merged.append(finding)
            naming_rank = rank
    return merged


def _replace(text: str, findings: list[Finding]) -> str:
    parts: list[str] = []
    done = 0
    for finding in findings:
        parts += [text[done : finding.start], f"[{finding.kind}]"]
        done = finding.end
    return "".join([*parts, text[done:]])


def _listed(option: str, values: Iterable[str]) -> list[str]:
    if isinstance(values, str):
        raise TypeError(f"{option}= takes a list, like {option}=[{values!r}]")
    return list(values)


def _holds_no_secret(value: object) -> bool:
    return value is None or isinstance(value, bool)


def _shown_as(value: object) -> str | None:
    """Return the text a value would be shown as, or None when it can't be turned into text."""
    try:
        if isinstance(value, bytes | bytearray | memoryview):
            return bytes(value).decode(errors="replace")
        return str(value)
    except Exception:
        return None


class Redactor:
    """Cleans any value, leaving a Placeholder such as [EMAIL] where each sensitive one was."""

    __slots__ = ("_detectors", "_names")

    def __init__(
        self,
        *,
        detectors: Iterable[Detector] = (),
        names: Iterable[str] = (),
        without: Iterable[str] = (),
        allow_names: Iterable[str] = (),
    ) -> None:
        off = set(_listed("without", without))
        built_in = (detector for kind, detector in BUILT_IN.items() if kind not in off)
        self._names = SensitiveNames(_listed("names", names), _listed("allow_names", allow_names))
        # Sensitive names come first, so a value hidden by name is always [REDACTED].
        self._detectors = (self._names.find_values, *built_in, *detectors)

    @overload
    def __call__(self, value: str) -> str: ...

    @overload
    def __call__(self, value: object) -> object: ...

    def __call__(self, value: object) -> object:
        return self._clean(value, set())

    def _clean(self, value: object, parents: set[int]) -> object:
        """Clean one value. `parents` holds the structures this value sits inside."""
        if _holds_no_secret(value):
            return value
        if isinstance(value, dict | list | tuple | set | frozenset):
            return self._clean_structure(value, parents)
        text = _shown_as(value)
        if text is None:
            return f"[UNPRINTABLE {type(value).__name__}]"
        cleaned = self._clean_text(text)
        return value if isinstance(value, Number) and cleaned == text else cleaned

    def _clean_structure(self, value: Iterable[object], parents: set[int]) -> object:
        if id(value) in parents or len(parents) >= _MAX_DEPTH:
            return _HIDDEN
        parents.add(id(value))
        cleaned: object
        if isinstance(value, dict):
            cleaned = {
                self._clean(key, parents): self._clean_field(key, item, parents)
                for key, item in value.items()
            }
        elif isinstance(value, tuple) and isinstance(
            fields := getattr(value, "_fields", None), tuple
        ):
            pairs = zip(fields, value, strict=True)
            items = [self._clean_field(field, item, parents) for field, item in pairs]
            cleaned = tuple.__new__(type(value), items)
        else:
            shape = next(kind for kind in _SHAPES if isinstance(value, kind))
            cleaned = shape([self._clean(item, parents) for item in value])
        parents.remove(id(value))
        return cleaned

    def _clean_field(self, key: object, item: object, parents: set[int]) -> object:
        name = None if isinstance(key, Number | tuple | frozenset) else _shown_as(key)
        if name is not None and not _holds_no_secret(item) and self._names.hide(name):
            return _HIDDEN
        return self._clean(item, parents)

    def _clean_text(self, text: str) -> str:
        return _replace(text, _find(text, self._detectors))
