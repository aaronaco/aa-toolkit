"""An app finding where sensitive values sit in text without replacing them."""

import importlib.util
from pathlib import Path

import pytest

from aa_redact import Finding, Redactor, known_values, pattern

TESTS_DIR = Path(__file__).resolve().parent
AWS_KEY = "AK" + "IA" + "IOSFODNN7EXAMPLE"


def spans(*findings):
    """A Detector that reports the given (kind, start, end) Findings."""
    return lambda text: [Finding(*finding) for finding in findings]


OVERLAP_CASES = [
    (
        Redactor(detectors=[spans(("SHORT", 2, 5)), spans(("LONG", 3, 8))]),
        "0123456789",
        [Finding("LONG", 2, 8)],
        "01[LONG]89",
    ),
    (
        Redactor(detectors=[pattern("HOST", r"example\.com")]),
        "ask bob@example.com or see example.com",
        [Finding("EMAIL", 4, 19), Finding("HOST", 27, 38)],
        "ask [EMAIL] or see [HOST]",
    ),
    (
        Redactor(detectors=[spans(("FIRST", 0, 4)), spans(("SECOND", 2, 6))]),
        "0123456789",
        [Finding("FIRST", 0, 6)],
        "[FIRST]6789",
    ),
    (
        Redactor(detectors=[spans(("SECOND", 2, 6)), spans(("FIRST", 0, 4))]),
        "0123456789",
        [Finding("SECOND", 0, 6)],
        "[SECOND]6789",
    ),
    (
        Redactor(detectors=[pattern("CONTACT", r"\S+@\S+")]),
        "ask bob@example.com today",
        [Finding("EMAIL", 4, 19)],
        "ask [EMAIL] today",
    ),
    (
        Redactor(detectors=[spans(("A", 0, 3)), spans(("B", 2, 6)), spans(("C", 5, 8))]),
        "0123456789",
        [Finding("B", 0, 8)],
        "[B]89",
    ),
    (
        Redactor(detectors=[spans(("A", 0, 3), ("B", 2, 4), ("C", 3, 9))]),
        "0123456789",
        [Finding("C", 0, 9)],
        "[C]9",
    ),
    (
        Redactor(detectors=[spans(("A", 0, 2), ("B", 2, 4))]),
        "0123456789",
        [Finding("A", 0, 2), Finding("B", 2, 4)],
        "[A][B]456789",
    ),
]


def parametrized(filename, argnames, *, test_name=None):
    """Read the parametrized cases for `argnames` from an existing test module."""
    path = TESTS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [
        case
        for name, item in vars(module).items()
        if test_name is None or name == test_name
        for mark in getattr(item, "pytestmark", ())
        if mark.name == "parametrize" and mark.args[0] == argnames
        for case in mark.args[1]
    ]


def test_find_returns_the_finding_and_leaves_the_text_unchanged():
    redact = Redactor()
    text = "mail jane@corp.com"

    findings = redact.find(text)

    assert findings == [Finding("EMAIL", 5, 18)]
    assert text[5:18] == "jane@corp.com"
    assert text == "mail jane@corp.com"
    assert "jane@corp.com" not in repr(findings)


def test_find_returns_an_empty_list_when_nothing_in_the_text_is_sensitive():
    assert Redactor().find("order 4521 shipped") == []
    assert Redactor().find("") == []


def test_find_returns_several_sensitive_values_in_text_order():
    text = f"mail jane@corp.com or key {AWS_KEY}"

    assert Redactor().find(text) == [
        Finding("EMAIL", 5, 18),
        Finding("AWS_ACCESS_KEY", 26, 46),
    ]


def test_find_orders_findings_from_a_generator_detector_that_yields_backwards():
    def backwards(text):
        yield Finding("LAST", len(text) - 1, len(text))
        yield Finding("FIRST", 0, 1)

    assert Redactor(detectors=[backwards]).find("a-b-c") == [
        Finding("FIRST", 0, 1),
        Finding("LAST", 4, 5),
    ]


@pytest.mark.parametrize(("redact", "text", "expected_findings", "_"), OVERLAP_CASES)
def test_find_merges_overlapping_findings_with_the_same_span_and_kind_as_replacing(
    redact, text, expected_findings, _
):
    assert redact.find(text) == expected_findings


def test_find_reports_a_value_under_a_sensitive_name_as_redacted():
    text = "password=hunter2"

    assert Redactor().find(text) == [Finding("REDACTED", 9, 16)]
    assert text[9:16] == "hunter2"
    assert Redactor().find("password=bob@example.com") == [Finding("REDACTED", 9, 24)]


def test_find_applies_custom_detectors_known_values_names_without_and_allow_names():
    tax_id = pattern("TAX_ID", r"\b\d{3}-\d{3}-\d{3}\b")
    db_pw = known_values("DB_PASSWORD", ["p@ss/w0rd", ""])
    redact = Redactor(
        detectors=[tax_id, db_pw],
        names=["ssn"],
        without=["EMAIL"],
        allow_names=["password_length", "password_hint"],
    )
    text = (
        "tax 123-456-789 for bob@example.com "
        "pw=p%40ss%2Fw0rd customer_ssn=999 "
        "password_length=12 password_hint=123-456-789"
    )

    assert redact.find(text) == [
        Finding("TAX_ID", 4, 15),
        Finding("DB_PASSWORD", 39, 52),
        Finding("REDACTED", 66, 69),
        Finding("TAX_ID", 103, 114),
    ]


def existing_cases():
    """Every text input from the existing text, Sensitive names, Known values and overlap tests."""
    default = Redactor()
    allow_pw_length = Redactor(allow_names=["password_length"])
    cases = [
        (
            default,
            "order 4521 for bob.smith@example.com, paid 12.50",
            "order 4521 for [EMAIL], paid 12.50",
        ),
        *(
            (default, text, cleaned)
            for text, cleaned in parametrized("test_text.py", ("text", "cleaned"))
        ),
        *((default, text, text) for text in parametrized("test_text.py", "text")),
        *(
            (default, text, cleaned)
            for text, cleaned in parametrized("test_sensitive_names.py", ("text", "cleaned"))
        ),
        *(
            (default, text, text)
            for name in (
                "test_text_with_no_value_under_a_sensitive_name_is_unchanged",
                "test_a_quoted_name_with_spaces_that_is_not_sensitive_stays",
            )
            for text in parametrized("test_sensitive_names.py", "text", test_name=name)
        ),
        *(
            (allow_pw_length, text, text)
            for text in parametrized(
                "test_sensitive_names.py",
                "text",
                test_name="test_allow_names_keeps_a_pair_in_text_visible",
            )
        ),
        (default, "password='abc def", "password='[REDACTED]"),
        (default, "password=bob@example.com", "password=[REDACTED]"),
        (default, "Cookie: a=1; sid=abc\nHost: db", "Cookie: [REDACTED]\nHost: db"),
        (
            Redactor(names=["ssn"]),
            "customer_ssn=123 ssn_last4=4",
            "customer_ssn=[REDACTED] ssn_last4=4",
        ),
        (
            Redactor(allow_names=["token"]),
            "token=abc access_token=def",
            "token=abc access_token=[REDACTED]",
        ),
        (
            Redactor(allow_names=["password_hint"]),
            "password_hint=bob@example.com",
            "password_hint=[EMAIL]",
        ),
        (default, f"{'a' * 300}_password=abc", f"{'a' * 300}_password=[REDACTED]"),
        (
            default,
            '{"note": "a b", "user": "bob", "password": "abc"}',
            '{"note": "a b", "user": "bob", "password": "[REDACTED]"}',
        ),
        *(
            (Redactor(detectors=[known_values("DB_PASSWORD", [value])]), text, cleaned)
            for value, text, cleaned in parametrized(
                "test_known_values.py", ("value", "text", "cleaned")
            )
        ),
        *(
            (
                Redactor(
                    detectors=[
                        known_values("DB_PASSWORD", [longer, shorter] if rev else [shorter, longer])
                    ]
                ),
                f"first {longer} and then {shorter}",
                "first [DB_PASSWORD] and then [DB_PASSWORD]",
            )
            for shorter, longer in parametrized("test_known_values.py", ("shorter", "longer"))
            for rev in (False, True)
        ),
        (
            Redactor(detectors=[known_values("DB_PASSWORD", ["correct-horse-battery-staple"])]),
            "connect with correct-horse-battery-staple failed",
            "connect with [DB_PASSWORD] failed",
        ),
        (
            Redactor(detectors=[known_values("DB_PASSWORD", ["ab%2Fcd"])]),
            "ab%2Fcd and ab%2fcd",
            "[DB_PASSWORD] and ab%2fcd",
        ),
        (
            Redactor(detectors=[known_values("DB_PASSWORD", ["hunter", "ter2"])]),
            "pw is hunter2 today",
            "pw is [DB_PASSWORD] today",
        ),
        (
            Redactor(detectors=[known_values("DB_PASSWORD", ["", "hunter2"])]),
            "connect with hunter2 failed",
            "connect with [DB_PASSWORD] failed",
        ),
        (
            Redactor(detectors=[known_values("DB_PASSWORD", [r"p$w.*[1]+?(a|b)^\\"])]),
            r"pw p$w.*[1]+?(a|b)^\\ and p$w991a",
            "pw [DB_PASSWORD] and p$w991a",
        ),
        *((redact, text, cleaned) for redact, text, _, cleaned in OVERLAP_CASES),
    ]
    assert len(cases) >= 180
    return cases


@pytest.mark.parametrize(("redact", "text", "expected"), existing_cases())
def test_replacing_each_finding_with_its_placeholder_equals_what_the_redactor_returns(
    redact, text, expected
):
    findings = redact.find(text)
    placed = text
    for finding in reversed(findings):
        placed = f"{placed[: finding.start]}[{finding.kind}]{placed[finding.end :]}"

    assert placed == redact(text) == expected


def test_find_returns_only_findings_that_start_before_the_size_limit():
    redact = Redactor(max_length=12)

    assert redact.find("user: jane@corp.com and key " + AWS_KEY) == [Finding("EMAIL", 6, 19)]
    assert redact.find("012345678901 jane@corp.com") == []
    assert Redactor().find("a" * (64 * 1024) + " jane@corp.com") == []


def test_find_does_not_read_past_the_limit_and_longest_value():
    seen = []
    prefix = "a" * 100 + "b" * (64 * 1024)

    def spy(text):
        seen.append(text)
        return []

    Redactor(detectors=[spy], max_length=100).find(prefix + "c" * 100_000)

    assert seen == [prefix]


def broken_detector(text):
    raise LookupError("no table of tax ids")


def broken_generator(text):
    yield Finding("FIRST", 0, 1)
    raise LookupError("stopped early")


@pytest.mark.parametrize(
    ("detector", "error", "match"),
    [
        (broken_detector, LookupError, "no table of tax ids"),
        (broken_generator, LookupError, "stopped early"),
        *(
            (lambda text, span=span: [Finding("TAX_ID", *span)], ValueError, "TAX_ID")
            for span in ((-1, 2), (2, 4), (0, 0), (2, 1), (3, 3))
        ),
    ],
)
def test_find_raises_the_same_error_as_replacing_when_a_detector_fails(detector, error, match):
    redact = Redactor(detectors=[detector])

    with pytest.raises(error, match=match) as from_replace:
        redact("abc")
    with pytest.raises(error, match=match) as from_find:
        redact.find("abc")

    assert type(from_find.value) is type(from_replace.value)
    assert str(from_find.value) == str(from_replace.value)


@pytest.mark.parametrize(
    ("value", "type_name"),
    [
        ({"email": "jane@corp.com", "other": "x"}, "dict"),
        (["jane@corp.com"], "list"),
        (b"jane@corp.com", "bytes"),
        (bytearray(b"jane@corp.com"), "bytearray"),
        (42, "int"),
        (3.14, "float"),
        (None, "NoneType"),
    ],
)
def test_find_given_a_value_that_is_not_text_raises_and_names_the_type(value, type_name):
    with pytest.raises(TypeError, match=type_name):
        Redactor().find(value)
    with pytest.raises(TypeError, match=type_name):
        Redactor(max_length=1).find(value)
