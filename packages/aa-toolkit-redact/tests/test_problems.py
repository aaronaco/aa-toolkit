"""What an app sees when a Detector is wrong or fails."""

import re

import pytest

from aa_redact import Finding, Redactor, pattern


def test_an_invalid_regex_raises_when_the_pattern_is_made_and_not_when_text_is_checked():
    with pytest.raises(re.error):
        pattern("TAX_ID", r"(\d{3}-\d{3}")


def test_an_error_in_a_detector_comes_out_of_the_redactor():
    def broken(text):
        raise LookupError("no table of tax ids")

    redact = Redactor(detectors=[broken])

    with pytest.raises(LookupError, match="no table of tax ids"):
        redact("tax id 123-456-789")


def test_an_error_partway_through_a_generator_detector_comes_out_of_the_redactor():
    def broken(text):
        yield Finding("FIRST", 0, 1)
        raise LookupError("stopped early")

    with pytest.raises(LookupError, match="stopped early"):
        Redactor(detectors=[broken])("abc")


@pytest.mark.parametrize(
    "span",
    [(-1, 2), (2, 4), (0, 0), (2, 1), (3, 3)],
    ids=["starts before the text", "ends after the text", "empty", "backwards", "at the end"],
)
def test_a_finding_that_does_not_fit_the_text_raises_and_names_the_kind(span):
    redact = Redactor(detectors=[lambda text: [Finding("TAX_ID", *span)]])

    with pytest.raises(ValueError, match="TAX_ID"):
        redact("abc")


def test_a_pattern_that_can_match_nothing_finds_only_real_matches():
    redact = Redactor(detectors=[pattern("DIGITS", r"\d*")])

    assert redact("ab 123 cd") == "ab [DIGITS] cd"
