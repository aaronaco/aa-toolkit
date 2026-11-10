"""An app naming the exact secrets it already holds with known_values()."""

import pytest

from aa_redact import Redactor, known_values


def test_a_known_value_becomes_a_placeholder_for_its_kind():
    redact = Redactor(detectors=[known_values("DB_PASSWORD", ["correct-horse-battery-staple"])])

    assert (
        redact("connect with correct-horse-battery-staple failed")
        == "connect with [DB_PASSWORD] failed"
    )


@pytest.mark.parametrize(
    ("value", "text", "cleaned"),
    [
        ("p@ss/w0rd?1", "url?k=p%40ss%2Fw0rd%3F1&x=2", "url?k=[DB_PASSWORD]&x=2"),
        ("p@ss/w0rd?1", "url?k=p%40ss/w0rd%3F1&x=2", "url?k=[DB_PASSWORD]&x=2"),
        ("p@ss/w0rd?1", "url?k=p%40ss%2fw0rd%3f1&x=2", "url?k=[DB_PASSWORD]&x=2"),
        ("my secret/1", "form?k=my+secret%2F1&x=2", "form?k=[DB_PASSWORD]&x=2"),
        ("my secret/1", "form?k=my%20secret%2F1&x=2", "form?k=[DB_PASSWORD]&x=2"),
    ],
)
def test_a_known_value_that_is_url_encoded_is_hidden(value, text, cleaned):
    redact = Redactor(detectors=[known_values("DB_PASSWORD", [value])])

    assert redact(text) == cleaned


@pytest.mark.parametrize(
    ("value", "text", "cleaned"),
    [
        ('p"ss\\w0rd', r'{"k": "p\"ss\\w0rd"}', '{"k": "[DB_PASSWORD]"}'),
        ("line1\nline2\t!", r'{"k": "line1\nline2\t!"}', '{"k": "[DB_PASSWORD]"}'),
        ('café"1', r'{"k": "caf\u00e9\"1"}', '{"k": "[DB_PASSWORD]"}'),
        ('café"1', r'{"k": "café\"1"}', '{"k": "[DB_PASSWORD]"}'),
        ("a/b/c", r'{"k": "a\/b\/c"}', '{"k": "[DB_PASSWORD]"}'),
        ('p"ss\\w0rd', r'\"k\": \"p\\\"ss\\\\w0rd\"', r'\"k\": \"[DB_PASSWORD]\"'),
    ],
)
def test_a_known_value_that_is_json_escaped_is_hidden(value, text, cleaned):
    redact = Redactor(detectors=[known_values("DB_PASSWORD", [value])])

    assert redact(text) == cleaned


@pytest.mark.parametrize("values", [[], [""], ["", ""]])
def test_an_empty_known_value_is_ignored_and_the_text_is_unchanged(values):
    redact = Redactor(detectors=[known_values("DB_PASSWORD", values)])

    assert redact("order 4521 shipped") == "order 4521 shipped"


def test_an_empty_known_value_next_to_a_real_one_leaves_the_real_one_working():
    redact = Redactor(detectors=[known_values("DB_PASSWORD", ["", "hunter2"])])

    assert redact("connect with hunter2 failed") == "connect with [DB_PASSWORD] failed"


@pytest.mark.parametrize(
    ("shorter", "longer"),
    [
        ("hunter", "hunter2"),
        ("s3cr3t", "s3cr3t_key"),
        ("ter", "hunter2"),
        ("ter2", "hunter2"),
        ("a@b", "a@b/c"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_a_known_value_that_contains_a_shorter_one_is_matched_whole(shorter, longer, reverse):
    values = [longer, shorter] if reverse else [shorter, longer]
    redact = Redactor(detectors=[known_values("DB_PASSWORD", values)])

    assert (
        redact(f"first {longer} and then {shorter}")
        == "first [DB_PASSWORD] and then [DB_PASSWORD]"
    )


def test_a_known_value_with_regex_characters_is_matched_as_plain_text():
    value = "p$w.*[1]+?(a|b)^\\"
    redact = Redactor(detectors=[known_values("DB_PASSWORD", [value])])

    assert redact(f"pw {value} and p$w991a") == "pw [DB_PASSWORD] and p$w991a"


def test_a_known_values_detector_does_not_change_when_the_list_it_was_given_changes():
    values = ["hunter2"]
    redact = Redactor(detectors=[known_values("DB_PASSWORD", values)])

    values.clear()

    assert redact("connect with hunter2 failed") == "connect with [DB_PASSWORD] failed"


def test_a_single_value_passed_as_text_and_not_a_list_raises_when_the_detector_is_made():
    with pytest.raises(TypeError, match="values"):
        known_values("DB_PASSWORD", "hunter2")
