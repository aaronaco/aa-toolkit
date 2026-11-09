"""Findings that overlap become one Placeholder."""

from aa_redact import Finding, Redactor, pattern


def spans(*findings):
    """A Detector that reports the given (kind, start, end) Findings."""
    return lambda text: [Finding(*finding) for finding in findings]


def test_overlapping_findings_become_one_placeholder_named_by_the_longest():
    redact = Redactor(detectors=[spans(("SHORT", 2, 5)), spans(("LONG", 3, 8))])

    assert redact("0123456789") == "01[LONG]89"


def test_a_finding_inside_a_longer_one_disappears_into_it():
    redact = Redactor(detectors=[pattern("HOST", r"example\.com")])

    assert redact("ask bob@example.com or see example.com") == "ask [EMAIL] or see [HOST]"


def test_the_earlier_detector_wins_when_overlapping_findings_are_the_same_length():
    first, second = spans(("FIRST", 0, 4)), spans(("SECOND", 2, 6))

    assert Redactor(detectors=[first, second])("0123456789") == "[FIRST]6789"
    assert Redactor(detectors=[second, first])("0123456789") == "[SECOND]6789"


def test_a_built_in_detector_is_earlier_than_one_the_app_adds():
    redact = Redactor(detectors=[pattern("CONTACT", r"\S+@\S+")])

    assert redact("ask bob@example.com today") == "ask [EMAIL] today"


def test_a_chain_of_overlaps_is_one_placeholder_with_nothing_left_between():
    redact = Redactor(
        detectors=[spans(("A", 0, 3)), spans(("B", 2, 6)), spans(("C", 5, 8))],
    )

    assert redact("0123456789") == "[B]89"


def test_the_longest_finding_names_the_placeholder_even_when_it_starts_last():
    redact = Redactor(detectors=[spans(("A", 0, 3), ("B", 2, 4), ("C", 3, 9))])

    assert redact("0123456789") == "[C]9"


def test_findings_that_only_touch_keep_their_own_placeholders():
    redact = Redactor(detectors=[spans(("A", 0, 2), ("B", 2, 4))])

    assert redact("0123456789") == "[A][B]456789"
