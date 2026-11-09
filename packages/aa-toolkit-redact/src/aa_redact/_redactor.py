"""Finding sensitive values in text and replacing them with Placeholders."""

from collections.abc import Iterable

from aa_redact._detectors import BUILT_IN
from aa_redact._finding import Detector, Finding


def _find(text: str, detectors: Iterable[Detector]) -> list[Finding]:
    """Return what the Detectors found, in text order, with overlaps merged into one Finding."""
    found = [
        (finding, order) for order, detector in enumerate(detectors) for finding in detector(text)
    ]
    for finding, _ in found:
        if not 0 <= finding.start < finding.end <= len(text):
            raise ValueError(f"a Detector returned a Finding that doesn't fit the text: {finding}")
    merged: list[Finding] = []
    best = (0, 0)  # the rank of the Finding that names the last merged one
    for finding, order in sorted(found, key=lambda item: item[0].start):
        rank = (finding.end - finding.start, -order)  # the longest wins, then the earlier Detector
        if merged and finding.start < merged[-1].end:
            last = merged[-1]
            kind = finding.kind if rank > best else last.kind
            merged[-1] = Finding(kind, last.start, max(last.end, finding.end))
            best = max(best, rank)
        else:
            merged.append(finding)
            best = rank
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
        off = set(without)
        built_in = (detector for kind, detector in BUILT_IN.items() if kind not in off)
        self._detectors = (*built_in, *detectors)

    def __call__(self, text: str) -> str:
        return _replace(text, _find(text, self._detectors))
