"""Finding sensitive values in text and replacing them with Placeholders."""

from collections.abc import Iterable

from aa_redact._detectors import BUILT_IN
from aa_redact._finding import Detector, Finding


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


class Redactor:
    """Replaces each sensitive value in text with a Placeholder such as [EMAIL]."""

    __slots__ = ("_detectors",)

    def __init__(self, *, detectors: Iterable[Detector] = (), without: Iterable[str] = ()) -> None:
        if isinstance(without, str):
            raise TypeError(f"without= takes a list of kinds, like without=[{without!r}]")
        off = set(without)
        built_in = (detector for kind, detector in BUILT_IN.items() if kind not in off)
        self._detectors = (*built_in, *detectors)

    def __call__(self, text: str) -> str:
        return _replace(text, _find(text, self._detectors))
