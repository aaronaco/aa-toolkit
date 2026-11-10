"""Text written to be slow can't stall an app."""

import time

import pytest

from aa_redact import Redactor

LENGTH = 64 * 1024
SECONDS_ALLOWED = 2  # a bounded pattern takes milliseconds, and a slow one takes minutes


def fill(piece: str) -> str:
    return (piece * (LENGTH // len(piece) + 1))[:LENGTH]


@pytest.mark.parametrize(
    "text",
    [
        fill("a"),
        fill("a")[:-1] + "@",
        fill("@"),
        fill("."),
        fill("a."),
        fill("a@"),
        fill("a@a."),
        "a@" + fill("a."),
        "a@" + fill("-"),
        fill("a" * 64 + "@"),
        fill("a" * 64 + "@" + ("b" * 63 + ".") * 8),
        fill("é"),
        fill("a'"),
        fill("'"),
        fill("a" * 64 + "'"),
        fill("e\u0301"),
        fill("\u0301"),
        "a@a." + fill("a\u0301"),
        "a@a." + fill("\u0301"),
        fill("a" * 64 + "@" + "a." * 126),
        fill("a" * 64 + "@" + ("b" * 63 + ".") * 126),
        "a@a.xn--" + fill("-"),
        fill("a@a.xn--"),
        fill("a@a.xn-"),
        fill("a@b.c "),
    ],
    ids=lambda text: repr(text[:12] + ".." + text[-6:]),
)
def test_the_built_in_detectors_stay_fast_on_long_awkward_text(text):
    redact = Redactor()

    started = time.perf_counter()
    redact(text)

    assert time.perf_counter() - started < SECONDS_ALLOWED
